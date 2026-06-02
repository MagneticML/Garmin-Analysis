"""Explore the structure of a Garmin .fit file (read straight from a .zip).

Run once just to see what's inside before we commit to a CSV schema.
"""

import io
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from fitparse import FitFile

DOWNLOADS = Path.home() / "Downloads"


def first_fit_zip() -> Path:
    zips = sorted(DOWNLOADS.glob("*.zip"))
    if not zips:
        raise SystemExit(f"No .zip files found in {DOWNLOADS}")
    return zips[0]


def load_fit_from_zip(zip_path: Path) -> FitFile:
    with zipfile.ZipFile(zip_path) as zf:
        fit_name = next(n for n in zf.namelist() if n.lower().endswith(".fit"))
        raw = zf.read(fit_name)
    return FitFile(io.BytesIO(raw))


def main() -> None:
    zip_path = first_fit_zip()
    print(f"Exploring: {zip_path.name}\n")

    fit = load_fit_from_zip(zip_path)

    # 1) What kinds of messages does this file contain, and how many of each?
    msg_counts = Counter()
    # collect the set of field names seen per message type
    fields_by_msg = defaultdict(set)

    for msg in fit.get_messages():
        msg_counts[msg.name] += 1
        for field in msg:
            fields_by_msg[msg.name].add(field.name)

    print("=== Message types (name: count) ===")
    for name, count in msg_counts.most_common():
        print(f"  {name:<20} {count}")

    # 2) Show the 'session' message — the per-run summary (distance, time, pace, HR...)
    print("\n=== SESSION fields (per-activity summary) ===")
    fit = load_fit_from_zip(zip_path)  # re-open; messages are a one-pass generator
    for msg in fit.get_messages("session"):
        for field in msg:
            print(f"  {field.name:<28} {field.value}  [{field.units or ''}]")

    # 3) Show the first couple of 'record' messages — the per-second samples
    print("\n=== First 3 RECORD messages (per-sample data) ===")
    fit = load_fit_from_zip(zip_path)
    shown = 0
    for msg in fit.get_messages("record"):
        print(f"  --- record {shown} ---")
        for field in msg:
            print(f"    {field.name:<24} {field.value}  [{field.units or ''}]")
        shown += 1
        if shown >= 3:
            break

    # 4) Field inventory across all message types (so we know our CSV options)
    print("\n=== All fields available, by message type ===")
    for name in sorted(fields_by_msg):
        print(f"  {name}:")
        for f in sorted(fields_by_msg[name]):
            print(f"      {f}")


if __name__ == "__main__":
    main()
