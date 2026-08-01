#!/usr/bin/env python3
"""Convert a copy-pasted dashboard table (tab-separated, "View as table") into
a CSV that OpenOffice/LibreOffice Calc opens cleanly -- real numbers, real
dates, blank cells instead of the on-page "—" placeholder.

Usage:
    python txt_to_csv.py test_data.txt test_data.csv
"""
import csv
import sys
from datetime import datetime

COLUMN_PARSERS = {
    "Time": lambda v: datetime.strptime(v, "%b %d, %Y, %I:%M %p").isoformat(sep=" "),
    "Level (cm)": float,
    "Temp (°C)": float,
    "Battery (V)": float,
    "RSSI (dBm)": int,
}

# Placeholders the dashboard uses in place of a real value (see dashboard.js
# tableColumns): "—" for a missing temp/battery/RSSI, "no echo" for a level
# reading where the HC-SR04 got no valid echo that wake.
BLANK_VALUES = {"", "—", "no echo"}


def convert(in_path, out_path):
    with open(in_path, newline="") as f:
        reader = csv.reader(f, delimiter="\t")
        header = next(reader)
        parsers = [COLUMN_PARSERS[col] for col in header]

        with open(out_path, "w", newline="") as out:
            writer = csv.writer(out)
            writer.writerow(header)
            for row in reader:
                writer.writerow(
                    parse(value) if value not in BLANK_VALUES else "" for parse, value in zip(parsers, row)
                )

    print(f"converted -> {out_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(f"usage: {sys.argv[0]} <input.txt> <output.csv>")
    convert(sys.argv[1], sys.argv[2])
