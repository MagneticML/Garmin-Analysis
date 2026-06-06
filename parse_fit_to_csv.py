"""Parse Garmin .fit running files (inside .zip exports) into a per-lap CSV.

Reads every *.zip in the data folder, pulls the single *_ACTIVITY.fit out of
each, and emits one row per lap with running-friendly units (miles, km, min/mile
pace, etc.) alongside the raw Garmin values.

Usage:
    python parse_fit_to_csv.py                       # uses the default folder below
    python parse_fit_to_csv.py "C:\\path\\to\\zips"    # or point it at any folder
"""

import csv
import io
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from fitparse import FitFile

# Where the Garmin .zip exports live. Override by passing a folder as the first
# command-line argument.
DEFAULT_DATA_DIR = Path.home() / "Documents" / "Garmin Files"


def resolve_data_dir():
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    return DEFAULT_DATA_DIR

# --- unit conversions ---------------------------------------------------------
METERS_PER_MILE = 1609.344
SEMICIRCLE_TO_DEG = 180.0 / (2 ** 31)


def to_miles(meters):
    return round(meters / METERS_PER_MILE, 4) if meters is not None else None


def to_km(meters):
    return round(meters / 1000.0, 4) if meters is not None else None


def semicircles_to_deg(value):
    return round(value * SEMICIRCLE_TO_DEG, 7) if value is not None else None


# FIT 'intensity' enum. fitparse resolves some (e.g. 'active', 'warmup') but
# leaves others as raw ints, so normalize the whole field to labels.
INTENSITY_LABELS = {
    0: "active", 1: "rest", 2: "warmup", 3: "cooldown",
    4: "recovery", 5: "interval", 6: "other",
}


def intensity_label(value):
    if value is None:
        return None
    if isinstance(value, int):
        return INTENSITY_LABELS.get(value, str(value))
    return value  # already a string label from fitparse


def fmt_duration(seconds):
    """Seconds -> 'H:MM:SS' (drops the hour when zero)."""
    if seconds is None:
        return None
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_pace(decimal_minutes):
    """Decimal minutes-per-unit -> 'M:SS' (e.g. 8.5 -> '8:30')."""
    if decimal_minutes is None:
        return None
    total_s = int(round(decimal_minutes * 60))
    m, s = divmod(total_s, 60)
    return f"{m}:{s:02d}"


def pace_from(distance_m, time_s):
    """Return (min_per_mile, min_per_km) as decimals computed from distance & time.

    This is more reliable than the watch's avg_speed field, which is sometimes
    blank, and it is exactly what a runner means by 'lap pace'.
    """
    if not distance_m or not time_s:
        return None, None
    sec_per_meter = time_s / distance_m
    min_per_mile = round(sec_per_meter * METERS_PER_MILE / 60.0, 4)
    min_per_km = round(sec_per_meter * 1000.0 / 60.0, 4)
    return min_per_mile, min_per_km


# --- field plumbing -----------------------------------------------------------
# Output columns in order. Each entry is (csv_column, how_to_get_it).
#   - str  -> raw lap field name, copied through as-is
#   - callable(lap_dict) -> computed value
def build_row(activity_id, source_file, lap):
    """lap is a dict of {field_name: value} for one 'lap' message."""

    def g(name):
        return lap.get(name)

    timer_time = g("total_timer_time")
    elapsed_time = g("total_elapsed_time")
    distance_m = g("total_distance")
    pace_mi, pace_km = pace_from(distance_m, timer_time)

    avg_cad = g("avg_running_cadence")
    max_cad = g("max_running_cadence")
    step_len_mm = g("avg_step_length")

    return {
        "activity_id": activity_id,
        "source_file": source_file,
        "sport": g("sport"),
        "sub_sport": g("sub_sport"),
        "lap_num": (g("message_index") + 1) if g("message_index") is not None else None,
        "workout_step": g("wkt_step_index"),
        "intensity": intensity_label(g("intensity")),  # active / rest / warmup / cooldown / recovery
        "lap_trigger": g("lap_trigger"),
        "start_time": g("start_time"),
        "end_time": g("timestamp"),
        # distance
        "distance_mi": to_miles(distance_m),
        "distance_km": to_km(distance_m),
        "distance_m": distance_m,
        # time
        "duration": fmt_duration(timer_time),
        "timer_time_s": timer_time,
        "elapsed_time_s": elapsed_time,
        # pace (computed from distance & timer time)
        "pace_per_mi": fmt_pace(pace_mi),
        "pace_per_km": fmt_pace(pace_km),
        "pace_min_per_mi": pace_mi,
        "pace_min_per_km": pace_km,
        "avg_speed_ms": g("enhanced_avg_speed") if g("enhanced_avg_speed") is not None else g("avg_speed"),
        "max_speed_ms": g("enhanced_max_speed") if g("enhanced_max_speed") is not None else g("max_speed"),
        # heart rate
        "avg_hr": g("avg_heart_rate"),
        "max_hr": g("max_heart_rate"),
        # cadence: watch records "strides/min" (one foot); steps/min = x2
        "avg_cadence_spm": (avg_cad * 2) if avg_cad is not None else None,
        "max_cadence_spm": (max_cad * 2) if max_cad is not None else None,
        "avg_cadence_strides_min": avg_cad,
        "total_strides": g("total_strides"),
        # running dynamics
        "avg_step_length_m": round(step_len_mm / 1000.0, 3) if step_len_mm is not None else None,
        "avg_vertical_oscillation_mm": g("avg_vertical_oscillation"),
        "avg_vertical_ratio_pct": g("avg_vertical_ratio"),
        "avg_stance_time_ms": g("avg_stance_time"),
        # effort
        "total_calories": g("total_calories"),
        "total_ascent_m": g("total_ascent"),
        "total_descent_m": g("total_descent"),
        # where the lap started
        "start_lat": semicircles_to_deg(g("start_position_lat")),
        "start_long": semicircles_to_deg(g("start_position_long")),
    }


def local_utc_offset(raw):
    """Offset (local - UTC) for this activity, or None if unavailable.

    FIT timestamps are stored in UTC, but the watch also records a
    `local_timestamp` in the 'activity' message. Their difference is the
    activity's UTC offset (DST-correct, since it's captured at record time),
    which we add to UTC timestamps to match what the Garmin app shows.
    """
    fit = FitFile(io.BytesIO(raw))
    for msg in fit.get_messages("activity"):
        utc = msg.get_value("timestamp")
        local = msg.get_value("local_timestamp")
        if utc and local:
            return local - utc
    return None


def iter_laps(zip_path):
    """Yield (activity_id, fit_filename, lap_dict) for each lap in a zip.

    Lap start_time / timestamp are converted from UTC to local time.
    """
    with zipfile.ZipFile(zip_path) as zf:
        fit_name = next(n for n in zf.namelist() if n.lower().endswith(".fit"))
        raw = zf.read(fit_name)

    activity_id = zip_path.stem  # e.g. "22938014424"
    offset = local_utc_offset(raw)
    fit = FitFile(io.BytesIO(raw))
    for msg in fit.get_messages("lap"):
        lap = {field.name: field.value for field in msg}
        if offset is not None:
            for key in ("start_time", "timestamp"):
                if isinstance(lap.get(key), datetime):
                    lap[key] = lap[key] + offset
        yield activity_id, fit_name, lap


def main():
    data_dir = resolve_data_dir()
    output_csv = data_dir / "garmin_laps.csv"

    if not data_dir.is_dir():
        raise SystemExit(f"Folder does not exist: {data_dir}")

    zips = sorted(data_dir.glob("*.zip"))
    if not zips:
        raise SystemExit(f"No .zip files found in {data_dir}")

    rows = []
    for zip_path in zips:
        n_before = len(rows)
        for activity_id, fit_name, lap in iter_laps(zip_path):
            rows.append(build_row(activity_id, fit_name, lap))
        print(f"  {zip_path.name}: {len(rows) - n_before} laps")

    if not rows:
        raise SystemExit("No lap messages found in any file.")

    # Sort by run start, then lap number, so the CSV reads chronologically.
    rows.sort(key=lambda r: (str(r["start_time"]), r["lap_num"] or 0))

    fieldnames = list(rows[0].keys())
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nWrote {len(rows)} lap rows from {len(zips)} runs -> {output_csv}")


if __name__ == "__main__":
    main()
