import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    env TEXT NOT NULL,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    bad_versions TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (env, name)
);
CREATE TABLE IF NOT EXISTS changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    env TEXT NOT NULL,
    to_version TEXT NOT NULL,
    from_version TEXT NOT NULL,
    risk TEXT NOT NULL CHECK (risk IN ('low','medium','high')),
    requester TEXT NOT NULL,
    approver TEXT,
    status TEXT NOT NULL CHECK (status IN
        ('requested','approved','deployed','rolled_back','rejected')),
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    change_id INTEGER,
    event TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
"""


def connect(path=":memory:"):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def log(conn, ts, change_id, event, detail=""):
    conn.execute(
        "INSERT INTO audit (ts, change_id, event, detail) VALUES (?,?,?,?)",
        (ts, change_id, event, detail),
    )
    conn.commit()
