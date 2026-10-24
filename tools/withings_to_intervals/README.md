# withings_to_intervals

Send your Withings weight, body fat and blood pressure history to intervals.icu without Withings+.

**For whom:** people with a Withings scale or blood pressure monitor who no longer get free
syncing to other apps and use intervals.icu (or just want their data in a clean CSV).

## Get your data from Withings

Withings lets everyone download their full history for free. In the Withings account
settings (the Withings website or Health Mate), request your data download, and you get a zip.
Menu names change, so check Withings' own help if you can't find it. The tool reads `weight.csv`
and `bp.csv` from that zip. You don't need to unpack it.

## Run it

Python 3.10 or newer, nothing to install.

Look first. This sends nothing:

```
python3 tools/withings_to_intervals/withings_to_intervals.py my_withings_export.zip
```

Only from one date on, and also write a clean CSV for a spreadsheet or another app:

```
python3 tools/withings_to_intervals/withings_to_intervals.py my_withings_export.zip --since 2026-01-01 --out clean.csv
```

Send to intervals.icu. In intervals.icu, open Settings > Developer Settings. There you find your
athlete id (looks like `i12345`) and can create an API key.

```
export INTERVALS_API_KEY=your-key
python3 tools/withings_to_intervals/withings_to_intervals.py my_withings_export.zip --send --athlete-id i12345
```

Sending again is safe: each day is overwritten with the same values.

## What it sends

One record per day, using the last measurement of that day:

| Withings | intervals.icu wellness field |
|---|---|
| weight (kg or lb, converted) | `weight` |
| body fat | `bodyFat` (percent, calculated from fat mass / weight if the export only has fat mass) |
| systolic, diastolic | `systolic`, `diastolic` |

The pulse from the blood pressure monitor is shown in the table and the clean CSV, but is **not**
sent as resting heart rate: it is not measured at rest overnight.

The column names are matched loosely (upper or lower case, kg or lb, comma or point as decimal).
The expected columns are `Date`, `Weight (kg)`, `Fat mass (kg)` in `weight.csv` and
`Date`, `Heart rate`, `Systolic`, `Diastolic` in `bp.csv`. This is based on the usual Withings
export format and was tested only on synthetic files. If your export looks different and
nothing is found, open an issue with the header line of your file (not your data).

## Options

`--help` lists everything: `--since`, `--out`, `--send`, `--dry-run` (the default),
`--athlete-id`, `--api-key`.

## What it does NOT do

- It does not use the Withings API and never asks for your Withings password.
- It does not upload anything to us or anyone but intervals.icu, and only with `--send`.
- It does not make FIT files for Garmin (maybe later).

## Where the data goes

Your files are read on your computer. With `--send`, the daily values go to intervals.icu
with your API key. The key is read from the option or the environment and is never printed or stored.

## Tests

```
python3 -m unittest discover -s tools/withings_to_intervals -t tools/withings_to_intervals -p "test_*.py"
```

They run offline on synthetic files in `samples/`.
