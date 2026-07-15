import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

DB_PATH = os.environ.get("WATER_TANK_DB", os.path.join(os.path.dirname(__file__), "data", "water_tank.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at TEXT NOT NULL,
    rssi INTEGER NOT NULL,
    wakeup_period_min INTEGER NOT NULL,
    avg_sample_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL REFERENCES requests(id),
    seq INTEGER NOT NULL,
    reading_time TEXT NOT NULL,
    distance_cm REAL,
    battery_mv INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_readings_reading_time ON readings(reading_time);

-- Single row (id=1): admin-desired device settings, pushed back to the
-- device in the ingest response until changed. NULL means "no override".
CREATE TABLE IF NOT EXISTS device_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    desired_wakeup_period_min INTEGER,
    desired_avg_sample_count INTEGER
);
INSERT OR IGNORE INTO device_config (id, desired_wakeup_period_min, desired_avg_sample_count)
VALUES (1, NULL, NULL);
"""


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_connection() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def insert_request(conn, received_at: str, rssi: int, wakeup_period_min: int, avg_sample_count: int) -> int:
    cur = conn.execute(
        "INSERT INTO requests (received_at, rssi, wakeup_period_min, avg_sample_count) VALUES (?, ?, ?, ?)",
        (received_at, rssi, wakeup_period_min, avg_sample_count),
    )
    return cur.lastrowid


def insert_reading(conn, request_id: int, seq: int, reading_time: str, distance_cm: float | None, battery_mv: int) -> None:
    conn.execute(
        "INSERT INTO readings (request_id, seq, reading_time, distance_cm, battery_mv) VALUES (?, ?, ?, ?, ?)",
        (request_id, seq, reading_time, distance_cm, battery_mv),
    )


def get_data_bounds(conn) -> tuple[datetime | None, datetime | None]:
    row = conn.execute("SELECT MIN(reading_time), MAX(reading_time) FROM readings").fetchone()
    if row is None or row[0] is None:
        return None, None
    return datetime.fromisoformat(row[0]), datetime.fromisoformat(row[1])


def get_readings(conn, start_iso: str, end_iso: str):
    return conn.execute(
        "SELECT reading_time, distance_cm, battery_mv FROM readings "
        "WHERE reading_time BETWEEN ? AND ? ORDER BY reading_time",
        (start_iso, end_iso),
    ).fetchall()


def get_desired_config(conn) -> tuple[int | None, int | None]:
    row = conn.execute(
        "SELECT desired_wakeup_period_min, desired_avg_sample_count FROM device_config WHERE id = 1"
    ).fetchone()
    return (row[0], row[1]) if row else (None, None)


def set_desired_config(conn, wakeup_period_min: int | None, avg_sample_count: int | None) -> None:
    conn.execute(
        "UPDATE device_config SET desired_wakeup_period_min = ?, desired_avg_sample_count = ? WHERE id = 1",
        (wakeup_period_min, avg_sample_count),
    )


def get_latest_reading(conn):
    return conn.execute(
        "SELECT reading_time, distance_cm, battery_mv FROM readings ORDER BY reading_time DESC LIMIT 1"
    ).fetchone()


def get_latest_request(conn):
    return conn.execute(
        "SELECT received_at, rssi, wakeup_period_min, avg_sample_count FROM requests ORDER BY id DESC LIMIT 1"
    ).fetchone()
