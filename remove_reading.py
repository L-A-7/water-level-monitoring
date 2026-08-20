#!/usr/bin/env python3
"""Search readings by date/time and interactively delete the wrong ones.

Usage:
    python remove_reading.py 2026-07-19            # every reading that day
    python remove_reading.py 2026-07-19T17:45      # narrow to a specific minute
    python remove_reading.py --id 1234             # look up a specific reading id

Matches are found with a prefix search against reading_time (ISO, UTC), so
any unambiguous prefix works. Nothing is deleted without an explicit 'yes'
confirmation, and the database is backed up first (deletion isn't reversible).
"""
import argparse
import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.environ.get("WATER_TANK_DB", os.path.join(os.path.dirname(__file__), "data", "water_tank.db"))

COLUMNS = ["id", "reading_time", "distance_cm", "distance_std_cm", "battery_mv", "chip_temp_c"]


def backup_db(db_path):
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = f"{db_path}.backup-{ts}"
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(backup_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    print(f"backed up {db_path} -> {backup_path}")
    return backup_path


def fmt_row(row):
    id_, reading_time, distance_cm, distance_std_cm, battery_mv, chip_temp_c = row
    distance = f"{distance_cm:.2f}cm" if distance_cm is not None else "no echo"
    if distance_std_cm is not None:
        distance += f" (±{distance_std_cm:.2f})"
    battery = f"{battery_mv}mV" if battery_mv is not None else "—"
    temp = f"{chip_temp_c:.1f}°C" if chip_temp_c is not None else "—"
    return f"id={id_:<6} {reading_time}  distance={distance:<20} battery={battery:<8} temp={temp}"


def find_by_prefix(conn, prefix):
    return conn.execute(
        f"SELECT {', '.join(COLUMNS)} FROM readings WHERE reading_time LIKE ? ORDER BY reading_time",
        (prefix + "%",),
    ).fetchall()


def find_by_id(conn, reading_id):
    return conn.execute(f"SELECT {', '.join(COLUMNS)} FROM readings WHERE id = ?", (reading_id,)).fetchall()


def prompt_selection(matches):
    print(f"\n{len(matches)} matching reading(s):\n")
    for i, row in enumerate(matches):
        print(f"  [{i}] {fmt_row(row)}")

    choice = input("\nDelete which? (index, comma-separated indices, 'a' for all, blank to cancel): ").strip()
    if not choice:
        return []
    if choice.lower() == "a":
        return matches
    try:
        indices = [int(x.strip()) for x in choice.split(",")]
        return [matches[i] for i in indices]
    except (ValueError, IndexError):
        print("Invalid selection, aborting.")
        return []


def delete_readings(db_path, conn, selected):
    print("\nAbout to permanently delete:")
    for row in selected:
        print(f"  {fmt_row(row)}")

    confirm = input(f"\nType 'yes' to delete {len(selected)} reading(s): ").strip()
    if confirm != "yes":
        print("Aborted, nothing deleted.")
        return

    backup_db(db_path)
    ids = [row[0] for row in selected]
    conn.executemany("DELETE FROM readings WHERE id = ?", [(i,) for i in ids])
    conn.commit()
    print(f"Deleted {len(ids)} reading(s).")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("query", nargs="?", help="date/time prefix to search for, e.g. 2026-07-19 or 2026-07-19T17:45")
    parser.add_argument("--id", type=int, help="look up a specific reading id instead of searching")
    parser.add_argument("--db", default=DB_PATH, help=f"path to water_tank.db (default: {DB_PATH})")
    args = parser.parse_args()

    if not args.query and args.id is None:
        parser.error("pass a date/time prefix to search, or --id")

    conn = sqlite3.connect(args.db)
    try:
        matches = find_by_id(conn, args.id) if args.id is not None else find_by_prefix(conn, args.query)
        if not matches:
            print("No matching readings found.")
            return
        selected = prompt_selection(matches)
        if selected:
            delete_readings(args.db, conn, selected)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
