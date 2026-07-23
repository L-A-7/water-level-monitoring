#!/usr/bin/env python3
"""Round-trip the readings table through CSV for manual editing.

    export: dump readings to CSV
    apply:  write edited values back, matched by id. Rows missing from the
            CSV are deleted by default (pass --no-allow-delete to instead
            leave them untouched). Every real apply (i.e. not --dry-run)
            backs up the database first, since deletion isn't reversible.

Usage:
    python csv_tool.py export readings.csv
    python csv_tool.py apply readings.csv --dry-run
    python csv_tool.py apply readings.csv
"""
import argparse
import csv
import os
import sqlite3
import sys
from datetime import datetime, timezone

DB_PATH = os.environ.get("WATER_TANK_DB", os.path.join(os.path.dirname(__file__), "data", "water_tank.db"))

COLUMNS = ["id", "request_id", "seq", "reading_time", "distance_cm", "battery_mv", "chip_temp_c"]


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


def export_csv(db_path, out_path):
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(f"SELECT {', '.join(COLUMNS)} FROM readings ORDER BY reading_time").fetchall()
    finally:
        conn.close()

    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        writer.writerows(rows)

    print(f"exported {len(rows)} rows to {out_path}")


def parse_row(r):
    return (
        r["reading_time"],
        float(r["distance_cm"]) if r["distance_cm"] not in ("", None) else None,
        int(r["battery_mv"]),
        float(r["chip_temp_c"]) if r["chip_temp_c"] not in ("", None) else None,
    )


def apply_csv(db_path, in_path, dry_run, allow_delete):
    with open(in_path, newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            sys.exit(f"CSV columns {reader.fieldnames} don't match expected {COLUMNS} -- "
                     f"don't add/remove/reorder columns, only edit values")
        edited_rows = list(reader)

    if not dry_run:
        backup_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        existing_ids = {row[0] for row in conn.execute("SELECT id FROM readings")}
        csv_ids = {int(r["id"]) for r in edited_rows}

        unknown = csv_ids - existing_ids
        if unknown:
            sys.exit(f"CSV has {len(unknown)} id(s) not in the database (e.g. {sorted(unknown)[:5]}) -- "
                      f"this script only updates existing rows, it can't insert new ones")

        missing = existing_ids - csv_ids
        if missing and not allow_delete:
            print(f"note: {len(missing)} row(s) in the database aren't in the CSV "
                  f"(e.g. id={sorted(missing)[:5]}) -- left unchanged (--no-allow-delete)")
        elif missing:
            print(f"{len(missing)} row(s) missing from the CSV will be DELETED: {sorted(missing)}")
            if not dry_run:
                conn.executemany("DELETE FROM readings WHERE id = ?", [(i,) for i in missing])

        changed = 0
        for r in edited_rows:
            row_id = int(r["id"])
            current = conn.execute(
                "SELECT reading_time, distance_cm, battery_mv, chip_temp_c FROM readings WHERE id = ?",
                (row_id,),
            ).fetchone()

            new_values = parse_row(r)
            if new_values == current:
                continue

            changed += 1
            print(f"id={row_id}: {current} -> {new_values}")
            if not dry_run:
                conn.execute(
                    "UPDATE readings SET reading_time=?, distance_cm=?, battery_mv=?, chip_temp_c=? WHERE id=?",
                    (*new_values, row_id),
                )

        deleted = len(missing) if allow_delete else 0
        if dry_run:
            print(f"\n{changed} row(s) would change, {deleted} would be deleted -- dry run, nothing written")
        else:
            conn.commit()
            print(f"\n{changed} row(s) updated, {deleted} deleted")
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=DB_PATH, help=f"path to water_tank.db (default: {DB_PATH})")
    sub = parser.add_subparsers(dest="command", required=True)

    export_p = sub.add_parser("export", help="dump readings table to CSV")
    export_p.add_argument("csv_path")

    apply_p = sub.add_parser("apply", help="apply an edited CSV back to the database")
    apply_p.add_argument("csv_path")
    apply_p.add_argument("--dry-run", action="store_true", help="show what would change without writing")
    apply_p.add_argument("--allow-delete", action=argparse.BooleanOptionalAction, default=True,
                          help="delete rows that exist in the database but are missing from the CSV "
                               "(default: on -- pass --no-allow-delete to leave missing rows untouched)")

    args = parser.parse_args()

    if args.command == "export":
        export_csv(args.db, args.csv_path)
    else:
        apply_csv(args.db, args.csv_path, args.dry_run, args.allow_delete)


if __name__ == "__main__":
    main()
