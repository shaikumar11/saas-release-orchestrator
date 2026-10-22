import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from releasectl import changes, cli, deploy, fleet
from releasectl.db import connect

WIN = ("2026-10-24 01:00", "2026-10-24 04:00")
IN_WINDOW = "2026-10-24 02:00"


def make(env="production", count=8, version="2.4.0"):
    conn = connect()
    fleet.add_nodes(conn, env, count, version)
    return conn


class RiskAndRequestTests(unittest.TestCase):
    def test_risk_levels(self):
        self.assertEqual(changes.risk_for("2.4.0", "2.4.1"), "low")
        self.assertEqual(changes.risk_for("2.4.0", "2.5.0"), "medium")
        self.assertEqual(changes.risk_for("2.4.0", "3.0.0"), "high")

    def test_rejects_bad_or_older_version(self):
        conn = make()
        with self.assertRaises(ValueError):
            changes.create(conn, "production", "2.5", "asha", *WIN, "t")
        with self.assertRaises(ValueError):
            changes.create(conn, "production", "2.3.9", "asha", *WIN, "t")

    def test_rejects_inverted_window(self):
        conn = make()
        with self.assertRaises(ValueError):
            changes.create(conn, "production", "2.4.1", "asha", WIN[1], WIN[0], "t")

    def test_staging_low_risk_auto_approved_production_needs_approval(self):
        conn = make("staging", 2)
        cid = changes.create(conn, "staging", "2.4.1", "asha", *WIN, "t")
        self.assertEqual(changes.get(conn, cid)["status"], "approved")
        prod = make("production")
        pid = changes.create(prod, "production", "2.4.1", "asha", *WIN, "t")
        self.assertEqual(changes.get(prod, pid)["status"], "requested")


class ApprovalTests(unittest.TestCase):
    def test_self_approval_blocked(self):
        conn = make()
        cid = changes.create(conn, "production", "2.5.0", "asha", *WIN, "t")
        with self.assertRaises(PermissionError):
            changes.approve(conn, cid, "asha", "t")

    def test_second_person_can_approve(self):
        conn = make()
        cid = changes.create(conn, "production", "2.5.0", "asha", *WIN, "t")
        changes.approve(conn, cid, "ravi", "t")
        self.assertEqual(changes.get(conn, cid)["approver"], "ravi")


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.conn = make()
        self.cid = changes.create(self.conn, "production", "2.5.0", "asha", *WIN, "t")

    def test_unapproved_change_blocked(self):
        with self.assertRaises(deploy.DeployError):
            deploy.deploy(self.conn, self.cid, IN_WINDOW)

    def test_outside_window_blocked(self):
        changes.approve(self.conn, self.cid, "ravi", "t")
        with self.assertRaises(deploy.DeployError):
            deploy.deploy(self.conn, self.cid, "2026-10-24 09:00")

    def test_freeze_day_blocked(self):
        changes.approve(self.conn, self.cid, "ravi", "t")
        with self.assertRaises(deploy.DeployError):
            deploy.deploy(self.conn, self.cid, IN_WINDOW, freeze_dates={"2026-10-24"})

    def test_unhealthy_fleet_blocked_and_untouched(self):
        changes.approve(self.conn, self.cid, "ravi", "t")
        fleet.inject_fault(self.conn, "production", "production-app-03", "2.4.0")
        with self.assertRaises(deploy.DeployError):
            deploy.deploy(self.conn, self.cid, IN_WINDOW)
        self.assertEqual(fleet.current_version(self.conn, "production"), "2.4.0")


class DeployTests(unittest.TestCase):
    def test_batches_start_with_canary(self):
        names = [f"n{i}" for i in range(8)]
        out = deploy.batches(names, 25)
        self.assertEqual(out[0], ["n0"])
        self.assertEqual([len(b) for b in out], [1, 2, 2, 2, 1])
        self.assertEqual(sum(out, []), names)

    def test_successful_rolling_deploy(self):
        conn = make()
        cid = changes.create(conn, "production", "2.5.0", "asha", *WIN, "t")
        changes.approve(conn, cid, "ravi", "t")
        self.assertEqual(deploy.deploy(conn, cid, IN_WINDOW), "deployed")
        self.assertEqual(fleet.current_version(conn, "production"), "2.5.0")
        self.assertEqual(changes.get(conn, cid)["status"], "deployed")

    def test_canary_failure_rolls_back_everything(self):
        conn = make()
        cid = changes.create(conn, "production", "2.5.0", "asha", *WIN, "t")
        changes.approve(conn, cid, "ravi", "t")
        fleet.inject_fault(conn, "production", "production-app-01", "2.5.0")
        self.assertEqual(deploy.deploy(conn, cid, IN_WINDOW), "rolled_back")
        self.assertEqual(fleet.current_version(conn, "production"), "2.4.0")
        events = [r["event"] for r in conn.execute("SELECT event FROM audit")]
        self.assertIn("health_check_failed", events)

    def test_mid_rollout_failure_restores_already_upgraded_nodes(self):
        conn = make()
        cid = changes.create(conn, "production", "2.5.0", "asha", *WIN, "t")
        changes.approve(conn, cid, "ravi", "t")
        fleet.inject_fault(conn, "production", "production-app-06", "2.5.0")
        self.assertEqual(deploy.deploy(conn, cid, IN_WINDOW), "rolled_back")
        self.assertEqual(fleet.current_version(conn, "production"), "2.4.0")
        self.assertEqual(changes.get(conn, cid)["status"], "rolled_back")

    def test_redeploy_after_success_is_blocked(self):
        conn = make()
        cid = changes.create(conn, "production", "2.4.1", "asha", *WIN, "t")
        changes.approve(conn, cid, "ravi", "t")
        deploy.deploy(conn, cid, IN_WINDOW)
        with self.assertRaises(deploy.DeployError):
            deploy.deploy(conn, cid, IN_WINDOW)


class CliTests(unittest.TestCase):
    def run_cli(self, db, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["--db", db, *argv])
        return code, out.getvalue(), err.getvalue()

    def test_end_to_end_flow_and_report(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "r.db")
            self.run_cli(db, "seed", "production", "4", "1.0.0")
            code, out, _ = self.run_cli(db, "request", "production", "1.1.0", "--by", "asha",
                                        "--start", WIN[0], "--end", WIN[1])
            self.assertIn("requested", out)
            code, _, err = self.run_cli(db, "approve", "1", "--by", "asha")
            self.assertEqual(code, 1)
            self.assertIn("cannot approve their own", err)
            self.run_cli(db, "approve", "1", "--by", "ravi")
            code, out, _ = self.run_cli(db, "deploy", "1", "--now", IN_WINDOW)
            self.assertEqual((code, out.strip()), (0, "change 1 deployed"))
            _, report, _ = self.run_cli(db, "report", "1")
            self.assertIn("deployed", report)

    def test_rollback_exit_code(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "r.db")
            self.run_cli(db, "seed", "production", "4", "1.0.0")
            self.run_cli(db, "request", "production", "1.1.0", "--by", "asha",
                         "--start", WIN[0], "--end", WIN[1])
            self.run_cli(db, "approve", "1", "--by", "ravi")
            self.run_cli(db, "fault", "production", "production-app-01", "1.1.0")
            code, out, _ = self.run_cli(db, "deploy", "1", "--now", IN_WINDOW)
            self.assertEqual(code, 2)
            self.assertIn("rolled_back", out)


if __name__ == "__main__":
    unittest.main()
