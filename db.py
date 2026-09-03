import os
import sqlite3
from collections.abc import Sequence
from contextlib import contextmanager
from datetime import datetime, timezone

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

def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        try:
            conn.execute("ALTER TABLE readings ADD COLUMN chip_temp_c REAL")
        except sqlite3.OperationalError:
            pass  # column already exists
        try:
            conn.execute("ALTER TABLE readings ADD COLUMN distance_std_cm REAL")
        except sqlite3.OperationalError:
            pass  # column already exists
        try:
            conn.execute("ALTER TABLE readings ADD COLUMN raw_samples_json TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists


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
    distance_std_cm: float | None = None,
    raw_samples_json: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO readings (request_id, seq, reading_time, distance_cm, battery_mv, chip_temp_c, "
        "distance_std_cm, raw_samples_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (request_id, seq, reading_time, distance_cm, battery_mv, chip_temp_c, distance_std_cm, raw_samples_json),
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
        SELECT r.reading_time, r.distance_cm, r.battery_mv, r.chip_temp_c, r.distance_std_cm,
               CASE WHEN r.seq = (SELECT MAX(seq) FROM readings WHERE request_id = r.request_id)
                    THEN q.rssi ELSE NULL END AS rssi
        FROM readings r
        JOIN requests q ON q.id = r.request_id
        WHERE r.reading_time BETWEEN ? AND ?
        ORDER BY r.reading_time
        """,
        (start_iso, end_iso),
    ).fetchall()


# Admin-only diagnostics (device.md's TEMPORARY samples_cm field): browse
# individual readings that carry a raw per-ping sample array. Most recent
# first, capped since every request only ever attaches raw samples to its
# one current-wake reading (never backlog), so this list grows slowly.
RAW_SAMPLE_READINGS_LIMIT = 500


def get_raw_sample_readings(conn):
    return conn.execute(
        """
        SELECT id, reading_time, distance_cm, distance_std_cm, raw_samples_json
        FROM readings
        WHERE raw_samples_json IS NOT NULL
        ORDER BY reading_time DESC
        LIMIT ?
        """,
        (RAW_SAMPLE_READINGS_LIMIT,),
    ).fetchall()


def get_raw_samples_for_reading(conn, reading_id: int):
    return conn.execute(
        "SELECT id, reading_time, distance_cm, distance_std_cm, raw_samples_json "
        "FROM readings WHERE id = ? AND raw_samples_json IS NOT NULL",
        (reading_id,),
    ).fetchone()


def get_readings_for_edit(conn, start_iso: str, end_iso: str):
    # Same shape as get_readings but keeps the row id, since the editor
    # targets individual readings for field-level erasure.
    return conn.execute(
        """
        SELECT r.id, r.reading_time, r.distance_cm, r.distance_std_cm, r.chip_temp_c, r.battery_mv,
               CASE WHEN r.seq = (SELECT MAX(seq) FROM readings WHERE request_id = r.request_id)
                    THEN q.rssi ELSE NULL END AS rssi
        FROM readings r
        JOIN requests q ON q.id = r.request_id
        WHERE r.reading_time BETWEEN ? AND ?
        ORDER BY r.reading_time
        """,
        (start_iso, end_iso),
    ).fetchall()


# Fields the admin data-editor is allowed to null out per reading, mapped to
# the columns each one covers. distance_std_cm rides along with water_level
# since it's just the noise estimate of that same (bad) distance measurement
# -- keeping it around after distance_cm is erased would be meaningless.
# battery_mv/rssi are NOT NULL (rssi also lives on the shared requests row,
# not per-reading) so they're intentionally not erasable here. "whole_reading"
# isn't a column-null op at all -- see delete_readings() below -- so it has
# no entry here.
ERASABLE_FIELD_COLUMNS = {
    "water_level": ("distance_cm", "distance_std_cm"),
    "temperature": ("chip_temp_c",),
}


def erase_reading_fields(conn, ids: list[int], fields: Sequence[str]) -> int:
    columns = [col for field in fields for col in ERASABLE_FIELD_COLUMNS[field]]
    if not columns or not ids:
        return 0
    set_clause = ", ".join(f"{col} = NULL" for col in columns)
    id_placeholders = ", ".join("?" for _ in ids)
    cur = conn.execute(
        f"UPDATE readings SET {set_clause} WHERE id IN ({id_placeholders})",
        ids,
    )
    return cur.rowcount


def delete_readings(conn, ids: list[int]) -> int:
    """Drop entire reading row(s) -- the "whole reading" erase option, for a
    point that's garbage across the board (not just one bad field). Doesn't
    touch the parent requests row, so a shared rssi stays intact for any
    other reading still in that request's backlog."""
    if not ids:
        return 0
    id_placeholders = ", ".join("?" for _ in ids)
    cur = conn.execute(f"DELETE FROM readings WHERE id IN ({id_placeholders})", ids)
    return cur.rowcount


def backup_before_delete() -> str:
    # Same approach as remove_reading.py's backup_db() -- whole-reading
    # deletion is irreversible, so snapshot the file first. Uses its own
    # connections outside of get_connection()'s transaction handling since
    # sqlite3's backup API needs to run against the live file, not a
    # yet-to-be-committed transaction.
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = f"{DB_PATH}.backup-{ts}"
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(backup_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return backup_path


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
