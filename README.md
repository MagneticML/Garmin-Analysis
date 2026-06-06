# Garmin Analysis

Tools for turning Garmin Connect `.fit` running exports into usable data.

## Files

- **`parse_fit_to_csv.py`** — Reads every `*.zip` in the data folder
  (`Documents/Garmin Files` by default, or a folder you pass as an argument),
  pulls the `*_ACTIVITY.fit` out of each, and writes one row **per lap** to
  `garmin_laps.csv` in that same folder, with running-friendly units (miles, km,
  min/mile pace, steps/min cadence) alongside the raw Garmin values.
- **`explore_fit.py`** — Inspection helper. Prints the message types, the per-run
  `session` summary, the first few per-second `record` samples, and a full field
  inventory for one `.fit` file. Use it to discover what else is available.

## Setup

```bash
pip install fitparse
```

## Usage

1. In Garmin Connect, export your activities (each downloads as a `.zip`
   containing one `_ACTIVITY.fit`). Put them in `Documents/Garmin Files`.
2. Run the parser:

   ```bash
   python parse_fit_to_csv.py                       # uses Documents/Garmin Files
   python parse_fit_to_csv.py "C:\path\to\zips"     # or any folder you choose
   ```

3. Open `garmin_laps.csv` in that same folder.

## Notes

- Pace is computed from distance ÷ timer time (more reliable than the watch's
  speed field, which is sometimes blank).
- `avg_cadence_spm` is steps/min (what the watch displays); the raw FIT field is
  strides/min (one foot), kept as `avg_cadence_strides_min`.
- Data files (`*.zip`, `*.fit`, `*.csv`) are gitignored — only the code is tracked.
