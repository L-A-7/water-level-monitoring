"""Sensor calibration history, stored in a plain text file so it can be
hand-edited (e.g. over SSH) as well as through the admin page.

File format: one entry per line, `start_iso, reference_offset_cm,
chip_temp_offset_c`. Entries don't carry an explicit end -- each one is in
effect from its start until the start of the next entry (sorted ascending);
the last line is the current calibration. Comment lines (`#`) and blank
lines are ignored, so the file can be re-sorted or annotated by hand freely.
"""

import os
import sqlite3
from datetime import datetime

CALIBRATION_FILE = os.environ.get(
    "WATER_TANK_CALIBRATION_FILE", os.path.join(os.path.dirname(__file__), "data", "calibration.txt")
)

# Seed values match the original config.py SENSOR_POSITION_HISTORY constants
# (TANK_HEIGHT_CM=350, sensor mounted at 50cm -> reference_offset_cm=300cm).
SEED_START = "2026-01-01T00:00:00+00:00"
SEED_REFERENCE_OFFSET_CM = 300.0
SEED_CHIP_TEMP_OFFSET_C = 0.0

HEADER = """\
# Sensor calibration history -- one entry per line:
#   start_iso, reference_offset_cm, chip_temp_offset_c
#
# reference_offset_cm collapses tank height + sensor mounting position into
# one constant: water_level_cm = reference_offset_cm - distance_cm
# chip_temp_offset_c is added to the raw onboard chip temperature reading.
#
# Each entry is in effect from its start until the start of the next one;
# the last line is the current calibration. Edit by hand and save, or use
# the admin page -- both read/write this same file.
"""


def _migrate_from_legacy_db() -> list[tuple[str, float, float]] | None:
    """One-time import from the old calibration_history DB table, if present."""
    import db as db_module

    if not os.path.exists(db_module.DB_PATH):
        return None
    conn = sqlite3.connect(db_module.DB_PATH)
    try:
        rows = conn.execute(
            "SELECT start, reference_offset_cm, chip_temp_offset_c FROM calibration_history ORDER BY start"
        ).fetchall()
        if rows:
            conn.execute("DROP TABLE calibration_history")
            conn.commit()
        return rows or None
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def init_calibration_file() -> None:
    if os.path.exists(CALIBRATION_FILE):
        return
    os.makedirs(os.path.dirname(CALIBRATION_FILE), exist_ok=True)
    rows = _migrate_from_legacy_db() or [(SEED_START, SEED_REFERENCE_OFFSET_CM, SEED_CHIP_TEMP_OFFSET_C)]
    with open(CALIBRATION_FILE, "w") as f:
        f.write(HEADER)
        for start, reference_offset_cm, chip_temp_offset_c in rows:
            f.write(f"{start}, {reference_offset_cm}, {chip_temp_offset_c}\n")


def load_history() -> list[tuple[datetime, float, float]]:
    """Full calibration history, sorted oldest first, for calibration.calibration_at()."""
    history = []
    with open(CALIBRATION_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            start_str, reference_offset_str, chip_temp_offset_str = (p.strip() for p in line.split(","))
            history.append((datetime.fromisoformat(start_str), float(reference_offset_str), float(chip_temp_offset_str)))
    history.sort(key=lambda row: row[0])
    return history


def get_current_calibration() -> tuple[float, float]:
    _, reference_offset_cm, chip_temp_offset_c = load_history()[-1]
    return reference_offset_cm, chip_temp_offset_c


def set_calibration(reference_offset_cm: float, chip_temp_offset_c: float, effective_at_iso: str) -> None:
    current_ref, current_temp_offset = get_current_calibration()
    if current_ref == reference_offset_cm and current_temp_offset == chip_temp_offset_c:
        return  # no change, avoid a no-op history entry
    with open(CALIBRATION_FILE, "a") as f:
        f.write(f"{effective_at_iso}, {reference_offset_cm}, {chip_temp_offset_c}\n")
