from .db import log


def add_nodes(conn, env, count, version, ts="init"):
    for i in range(1, count + 1):
        conn.execute(
            "INSERT INTO nodes (env, name, version) VALUES (?,?,?)",
            (env, f"{env}-app-{i:02d}", version),
        )
    conn.commit()
    log(conn, ts, None, "fleet_seeded", f"{env} x{count} at {version}")


def nodes(conn, env):
    return conn.execute(
        "SELECT * FROM nodes WHERE env=? ORDER BY name", (env,)
    ).fetchall()


def current_version(conn, env):
    versions = {n["version"] for n in nodes(conn, env)}
    if not versions:
        raise ValueError(f"no nodes in environment {env}")
    if len(versions) > 1:
        raise ValueError(f"mixed versions in {env}: {sorted(versions)}")
    return versions.pop()


def inject_fault(conn, env, name, bad_version):
    """Mark a node as unhealthy when it runs bad_version (failure simulation)."""
    conn.execute(
        "UPDATE nodes SET bad_versions=? WHERE env=? AND name=?",
        (bad_version, env, name),
    )
    conn.commit()


def is_healthy(node):
    bad = [v for v in node["bad_versions"].split(",") if v]
    return node["version"] not in bad
