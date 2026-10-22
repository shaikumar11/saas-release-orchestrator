"""Command line interface for releasectl."""
import argparse
import datetime
import sys

from . import changes, deploy, fleet
from .db import connect

DB = "releasectl.db"


def now_ts():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def build_parser():
    p = argparse.ArgumentParser(prog="releasectl", description=__doc__)
    p.add_argument("--db", default=DB)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("seed", help="create a simulated fleet")
    s.add_argument("env")
    s.add_argument("count", type=int)
    s.add_argument("version")

    s = sub.add_parser("status", help="show fleet versions")
    s.add_argument("env")

    s = sub.add_parser("request", help="raise a change request")
    s.add_argument("env")
    s.add_argument("version")
    s.add_argument("--by", required=True)
    s.add_argument("--start", required=True, help="YYYY-MM-DD HH:MM")
    s.add_argument("--end", required=True, help="YYYY-MM-DD HH:MM")

    s = sub.add_parser("approve")
    s.add_argument("change_id", type=int)
    s.add_argument("--by", required=True)

    s = sub.add_parser("deploy", help="canary then rolling deploy with auto rollback")
    s.add_argument("change_id", type=int)
    s.add_argument("--batch-percent", type=int, default=25)
    s.add_argument("--now", default=None, help="override clock for testing")

    s = sub.add_parser("fault", help="inject a failure for a node and version")
    s.add_argument("env")
    s.add_argument("node")
    s.add_argument("version")

    s = sub.add_parser("report", help="audit trail for a change")
    s.add_argument("change_id", type=int)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    conn = connect(args.db)
    try:
        if args.cmd == "seed":
            fleet.add_nodes(conn, args.env, args.count, args.version, now_ts())
        elif args.cmd == "status":
            for n in fleet.nodes(conn, args.env):
                state = "ok" if fleet.is_healthy(n) else "unhealthy"
                print(f"{n['name']}  {n['version']}  {state}")
        elif args.cmd == "request":
            cid = changes.create(conn, args.env, args.version, args.by,
                                 args.start, args.end, now_ts())
            print(f"change {cid} {changes.get(conn, cid)['status']}")
        elif args.cmd == "approve":
            changes.approve(conn, args.change_id, args.by, now_ts())
            print(f"change {args.change_id} approved")
        elif args.cmd == "deploy":
            result = deploy.deploy(conn, args.change_id, args.now or now_ts(),
                                   args.batch_percent)
            print(f"change {args.change_id} {result}")
            return 0 if result == "deployed" else 2
        elif args.cmd == "fault":
            fleet.inject_fault(conn, args.env, args.node, args.version)
        elif args.cmd == "report":
            for r in conn.execute("SELECT * FROM audit WHERE change_id=? ORDER BY id",
                                  (args.change_id,)):
                print(f"{r['ts']}  {r['event']:<20} {r['detail']}")
    except (ValueError, PermissionError, deploy.DeployError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())