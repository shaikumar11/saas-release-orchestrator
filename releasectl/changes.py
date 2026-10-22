import re

from . import fleet
from .db import log

SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
APPROVAL_REQUIRED_ENVS = {"production"}


def parse(version):
    m = SEMVER.match(version)
    if not m:
        raise ValueError(f"invalid version {version!r}, expected MAJOR.MINOR.PATCH")
    return tuple(int(x) for x in m.groups())


def risk_for(from_version, to_version):
    a, b = parse(from_version), parse(to_version)
    if b[0] != a[0]:
        return "high"
    if b[1] != a[1]:
        return "medium"
    return "low"


def create(conn, env, to_version, requester, window_start, window_end, now):
    current = fleet.current_version(conn, env)
    if parse(to_version) <= parse(current):
        raise ValueError(f"{to_version} is not newer than running {current}")
    if window_end <= window_start:
        raise ValueError("change window end must be after start")
    risk = risk_for(current, to_version)
    needs_approval = env in APPROVAL_REQUIRED_ENVS or risk == "high"
    status = "requested" if needs_approval else "approved"
    cur = conn.execute(
        "INSERT INTO changes (env, to_version, from_version, risk, requester, "
        "status, window_start, window_end) VALUES (?,?,?,?,?,?,?,?)",
        (env, to_version, current, risk, requester, status, window_start, window_end),
    )
    conn.commit()
    cid = cur.lastrowid
    log(conn, now, cid, "change_created",
        f"{env} {current}->{to_version} risk={risk} status={status}")
    return cid


def get(conn, change_id):
    row = conn.execute("SELECT * FROM changes WHERE id=?", (change_id,)).fetchone()
    if row is None:
        raise ValueError(f"change {change_id} not found")
    return row


def approve(conn, change_id, approver, now):
    ch = get(conn, change_id)
    if ch["status"] != "requested":
        raise ValueError(f"change {change_id} is {ch['status']}, cannot approve")
    if approver == ch["requester"]:
        raise PermissionError("requester cannot approve their own change")
    conn.execute(
        "UPDATE changes SET status='approved', approver=? WHERE id=?",
        (approver, change_id),
    )
    conn.commit()
    log(conn, now, change_id, "change_approved", f"by {approver}")


def reject(conn, change_id, approver, now):
    ch = get(conn, change_id)
    if ch["status"] != "requested":
        raise ValueError(f"change {change_id} is {ch['status']}, cannot reject")
    conn.execute("UPDATE changes SET status='rejected', approver=? WHERE id=?",
                 (approver, change_id))
    conn.commit()
    log(conn, now, change_id, "change_rejected", f"by {approver}")
