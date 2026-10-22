import math

from . import changes, fleet
from .db import log


class DeployError(Exception):
    pass


def _set_version(conn, env, names, version):
    conn.executemany(
        "UPDATE nodes SET version=? WHERE env=? AND name=?",
        [(version, env, n) for n in names],
    )
    conn.commit()


def _unhealthy(conn, env, names):
    rows = {n["name"]: n for n in fleet.nodes(conn, env)}
    return [n for n in names if not fleet.is_healthy(rows[n])]


def preflight(conn, change, now, freeze_dates=()):
    """Change-management gates that must pass before any node is touched."""
    if change["status"] != "approved":
        raise DeployError(f"change {change['id']} is {change['status']}, not approved")
    if not (change["window_start"] <= now <= change["window_end"]):
        raise DeployError(f"outside change window {change['window_start']} to {change['window_end']}")
    if now[:10] in freeze_dates:
        raise DeployError(f"change freeze in effect on {now[:10]}")
    env = change["env"]
    if fleet.current_version(conn, env) != change["from_version"]:
        raise DeployError("fleet drifted since the change was raised")
    bad = _unhealthy(conn, env, [n["name"] for n in fleet.nodes(conn, env)])
    if bad:
        raise DeployError(f"fleet unhealthy before deploy: {bad}")


def batches(names, batch_percent):
    """First batch is a single canary node, the rest follow in percentage batches."""
    if not 0 < batch_percent <= 100:
        raise ValueError("batch_percent must be between 1 and 100")
    size = max(1, math.ceil(len(names) * batch_percent / 100))
    out = [names[:1]]
    rest = names[1:]
    out += [rest[i:i + size] for i in range(0, len(rest), size)]
    return [b for b in out if b]


def deploy(conn, change_id, now, batch_percent=25, freeze_dates=()):
    ch = changes.get(conn, change_id)
    preflight(conn, ch, now, freeze_dates)
    env, new, old = ch["env"], ch["to_version"], ch["from_version"]
    names = [n["name"] for n in fleet.nodes(conn, env)]
    done = []
    log(conn, now, change_id, "deploy_started", f"{env} {old}->{new}")
    for i, group in enumerate(batches(names, batch_percent)):
        label = "canary" if i == 0 else f"batch {i}"
        _set_version(conn, env, group, new)
        done += group
        failed = _unhealthy(conn, env, group)
        if failed:
            _set_version(conn, env, done, old)
            conn.execute("UPDATE changes SET status='rolled_back' WHERE id=?", (change_id,))
            conn.commit()
            log(conn, now, change_id, "health_check_failed", f"{label}: {failed}")
            log(conn, now, change_id, "rolled_back", f"{len(done)} nodes restored to {old}")
            return "rolled_back"
        log(conn, now, change_id, "batch_healthy", f"{label}: {group}")
    conn.execute("UPDATE changes SET status='deployed' WHERE id=?", (change_id,))
    conn.commit()
    log(conn, now, change_id, "deployed", f"{len(done)} nodes on {new}")
    return "deployed"
