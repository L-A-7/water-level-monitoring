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
CREATE INDEX IF NOT EXISTS idx_readings_request_seq ON readings(request_id, seq);

-- Single row (id=1): admin-desired device settings, pushed back to the
-- device in the ingest response until changed. NULL means "no override".
CREATE TABLE IF NOT EXISTS device_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    desired_wakeup_period_min INTEGER,
    desired_avg_sample_count INTEGER
);
INSERT OR IGNORE INTO device_config (id, desired_wakeup_period_min, desired_avg_sample_count)
VALUES (1, NULL, NULL);

-- Sensor calibration over time: mirrors the old config.py
-- SENSOR_POSITION_HISTORY idea, but DB-backed and admin-editable. Each row
-- covers [start, end); end NULL means "still in effect". reference_offset_cm
-- collapses tank height and sensor mounting position into one constant
-- (water_level_cm = reference_offset_cm - distance_cm); chip_temp_offset_c is
-- added to the raw chip temperature reading.
CREATE TABLE IF NOT EXISTS calibration_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start TEXT NOT NULL,
    end TEXT,
    reference_offset_cm REAL NOT NULL,
    chip_temp_offset_c REAL NOT NULL
);

-- Single row (id=1): alert thresholds + email delivery settings, all
-- admin-editable. weak_signal has no subscribe flag -- it's a UI-only
-- warning (see admin_settings.html), never emailed.
CREATE TABLE IF NOT EXISTS alert_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    low_level_threshold_cm REAL NOT NULL,
    low_battery_threshold_v REAL NOT NULL,
    weak_signal_threshold_dbm INTEGER NOT NULL,
    submersed_threshold_cm REAL NOT NULL,
    recipient_email TEXT,
    subscribe_critical_low_level INTEGER NOT NULL,
    subscribe_low_battery INTEGER NOT NULL,
    subscribe_submersion_risk INTEGER NOT NULL
);
INSERT OR IGNORE INTO alert_config (
    id, low_level_threshold_cm, low_battery_threshold_v, weak_signal_threshold_dbm,
    submersed_threshold_cm, recipient_email,
    subscribe_critical_low_level, subscribe_low_battery, subscribe_submersion_risk
) VALUES (1, 20, 3.3, -85, 20, NULL, 1, 1, 1);

-- Per-alert-type latched state, so email dispatch is edge-triggered (fires
-- once on the inactive->active transition) instead of re-sending every
-- device check-in while a condition stays true.
CREATE TABLE IF NOT EXISTS alert_state (
    alert_type TEXT PRIMARY KEY,
    active INTEGER NOT NULL,
    last_triggered_at TEXT
);
"""

# Seed values match the retired config.py constants (TANK_HEIGHT_CM=350,
# SENSOR_POSITION_HISTORY starting 2026-01-01 at 50cm -> offset 300cm).
SEED_CALIBRATION_START = "2026-01-01T00:00:00+00:00"
SEED_REFERENCE_OFFSET_CM = 300.0
SEED_CHIP_TEMP_OFFSET_C = 0.0


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        try:
            conn.execute("ALTER TABLE readings ADD COLUMN chip_temp_c REAL")
        except sqlite3.OperationalError:
            pass  # column already exists

        row = conn.execute("SELECT COUNT(*) FROM calibration_history").fetchone()
        if row[0] == 0:
            conn.execute(
                "INSERT INTO calibration_history (start, end, reference_offset_cm, chip_temp_offset_c) "
                "VALUES (?, NULL, ?, ?)",
                (SEED_CALIBRATION_START, SEED_REFERENCE_OFFSET_CM, SEED_CHIP_TEMP_OFFSET_C),
            )


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


def insert_reading(
    conn,
    request_id: int,
    seq: int,
    reading_time: str,
    distance_cm: float | None,
    battery_mv: int,
    chip_temp_c: float | None = None,
) -> None:
    conn.execute(
        "INSERT INTO readings (request_id, seq, reading_time, distance_cm, battery_mv, chip_temp_c) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (request_id, seq, reading_time, distance_cm, battery_mv, chip_temp_c),
    )


def get_data_bounds(conn) -> tuple[datetime | None, datetime | None]:
    row = conn.execute("SELECT MIN(reading_time), MAX(reading_time) FROM readings").fetchone()
    if row is None or row[0] is None:
        return None, None
    return datetime.fromisoformat(row[0]), datetime.fromisoformat(row[1])


def get_readings(conn, start_iso: str, end_iso: str):
    # rssi is only meaningful for the reading that was actually live over
    # WiFi at connect time (the last seq in its request) -- backlog entries
    # flushed alongside it had no WiFi at capture time, per device.md.
    return conn.execute(
        """
        SELECT r.reading_time, r.distance_cm, r.battery_mv, r.chip_temp_c,
               CASE WHEN r.seq = (SELECT MAX(seq) FROM readings WHERE request_id = r.request_id)
                    THEN q.rssi ELSE NULL END AS rssi
        FROM readings r
        JOIN requests q ON q.id = r.request_id
        WHERE r.reading_time BETWEEN ? AND ?
        ORDER BY r.reading_time
        """,
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
        "SELECT reading_time, distance_cm, battery_mv, chip_temp_c FROM readings ORDER BY reading_time DESC LIMIT 1"
    ).fetchone()


def get_latest_request(conn):
    return conn.execute(
        "SELECT received_at, rssi, wakeup_period_min, avg_sample_count FROM requests ORDER BY id DESC LIMIT 1"
    ).fetchone()


def get_calibration_history(conn) -> list[tuple[datetime, "datetime | None", float, float]]:
    """Full calibration history, oldest first, for use with calibration.calibration_at()."""
    rows = conn.execute(
        "SELECT start, end, reference_offset_cm, chip_temp_offset_c FROM calibration_history ORDER BY start"
    ).fetchall()
    return [
        (datetime.fromisoformat(start), datetime.fromisoformat(end) if end else None, ref_cm, temp_offset_c)
        for start, end, ref_cm, temp_offset_c in rows
    ]


def get_current_calibration(conn) -> tuple[float, float]:
    row = conn.execute(
        "SELECT reference_offset_cm, chip_temp_offset_c FROM calibration_history WHERE end IS NULL"
    ).fetchone()
    return (row[0], row[1])


def set_calibration(conn, reference_offset_cm: float, chip_temp_offset_c: float, effective_at_iso: str) -> None:
    current_ref, current_temp_offset = get_current_calibration(conn)
    if current_ref == reference_offset_cm and current_temp_offset == chip_temp_offset_c:
        return  # no change, avoid a no-op history row
    conn.execute(
        "UPDATE calibration_history SET end = ? WHERE end IS NULL",
        (effective_at_iso,),
    )
    conn.execute(
        "INSERT INTO calibration_history (start, end, reference_offset_cm, chip_temp_offset_c) "
        "VALUES (?, NULL, ?, ?)",
        (effective_at_iso, reference_offset_cm, chip_temp_offset_c),
    )


def get_alert_config(conn) -> dict:
    row = conn.execute(
        "SELECT low_level_threshold_cm, low_battery_threshold_v, weak_signal_threshold_dbm, "
        "submersed_threshold_cm, recipient_email, subscribe_critical_low_level, "
        "subscribe_low_battery, subscribe_submersion_risk FROM alert_config WHERE id = 1"
    ).fetchone()
    return {
        "low_level_threshold_cm": row[0],
        "low_battery_threshold_v": row[1],
        "weak_signal_threshold_dbm": row[2],
        "submersed_threshold_cm": row[3],
        "recipient_email": row[4],
        "subscribe_critical_low_level": bool(row[5]),
        "subscribe_low_battery": bool(row[6]),
        "subscribe_submersion_risk": bool(row[7]),
    }


def set_alert_config(
    conn,
    low_level_threshold_cm: float,
    low_battery_threshold_v: float,
    weak_signal_threshold_dbm: int,
    submersed_threshold_cm: float,
    recipient_email: str | None,
    subscribe_critical_low_level: bool,
    subscribe_low_battery: bool,
    subscribe_submersion_risk: bool,
) -> None:
    conn.execute(
        """
        UPDATE alert_config SET
            low_level_threshold_cm = ?, low_battery_threshold_v = ?, weak_signal_threshold_dbm = ?,
            submersed_threshold_cm = ?, recipient_email = ?,
            subscribe_critical_low_level = ?, subscribe_low_battery = ?, subscribe_submersion_risk = ?
        WHERE id = 1
        """,
        (
            low_level_threshold_cm,
            low_battery_threshold_v,
            weak_signal_threshold_dbm,
            submersed_threshold_cm,
            recipient_email,
            int(subscribe_critical_low_level),
            int(subscribe_low_battery),
            int(subscribe_submersion_risk),
        ),
    )


def get_alert_state(conn, alert_type: str) -> bool:
    row = conn.execute("SELECT active FROM alert_state WHERE alert_type = ?", (alert_type,)).fetchone()
    return bool(row[0]) if row else False


def set_alert_state(conn, alert_type: str, active: bool, at_iso: str) -> None:
    conn.execute(
        "INSERT INTO alert_state (alert_type, active, last_triggered_at) VALUES (?, ?, ?) "
        "ON CONFLICT(alert_type) DO UPDATE SET active = excluded.active, last_triggered_at = excluded.last_triggered_at",
        (alert_type, int(active), at_iso),
    )
