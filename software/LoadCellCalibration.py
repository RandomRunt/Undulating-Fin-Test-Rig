"""Fit load-cell calibration from Thesis-DAQ option 3 CSV recordings.

Example (known forces in newtons):
    python software/LoadCellCalibration.py --point 0 zero.csv --point 9.80665 loaded.csv

Each --point accepts optional START_S END_S timestamps (seconds since device
boot) to select a settled interval in a recording. Use --output to save JSON.
Only Python's standard library is required.
"""

import argparse
import csv
import json
import math
from pathlib import Path
import statistics
import sys


# Helper function to check if a value is a finite number
def finite_number(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Expected a finite number, got {value!r}")
    return number


def read_point(path, force, start=None, end=None):
    """Average fresh force samples, ignoring monitor chatter and repeated headers."""
    samples = []
    header = None
    rejected = 0
    outside = 0
    chatter = 0
    dropped = 0
    required = {"time_us", "force_raw", "force_status", "dropped_lines"}
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.reader(stream):
            row = [field.strip() for field in row]
            if not row or not any(row):
                continue
            if row[0] == "time_us":
                if not required.issubset(row) or len(set(row)) != len(row):
                    raise ValueError(f"{path}: incompatible Thesis-DAQ CSV header")
                header = row
                continue
            # Menu/diagnostic output can surround CSV blocks in monitor logs.
            try:
                timestamp = int(row[0])
            except ValueError:
                chatter += 1
                continue
            if header is None:
                chatter += 1
                continue
            if len(row) != len(header) or timestamp < 0:
                rejected += 1
                continue
            seconds = timestamp / 1_000_000
            if (start is not None and seconds < start) or (end is not None and seconds > end):
                outside += 1
                continue
            record = dict(zip(header, row))
            try:
                lost = int(record["dropped_lines"])
                if lost < 0:
                    raise ValueError("negative dropped_lines")
                dropped = max(dropped, lost)
                if record["force_status"] != "ESP_OK":
                    raise ValueError("force sample unavailable")
                raw = int(record["force_raw"])
                if not -(2**23) <= raw < 2**23:
                    raise ValueError("raw count outside signed 24-bit ADC range")
            except ValueError:
                rejected += 1
                continue
            samples.append(raw)
    if header is None:
        raise ValueError(f"{path}: no Thesis-DAQ CSV header found; disable host timestamps")
    if len(samples) < 2:
        raise ValueError(f"{path}: need at least two valid force readings in the selected interval")
    return {
        "file": str(path), "known_force_N": force,
        "start_s": start, "end_s": end, "samples": len(samples),
        "mean_counts": statistics.mean(samples),
        "std_counts": statistics.stdev(samples),
        "rejected_rows": rejected, "outside_window_rows": outside,
        "ignored_log_lines": chatter, "max_dropped_lines": dropped,
    }


def fit_calibration(points):
    """Use equal weight per point and the same linear fit as Thesis-DAQ."""
    if len(points) < 2:
        raise ValueError("Provide at least two calibration points")
    if len({point["known_force_N"] for point in points}) < 2:
        raise ValueError("Calibration requires at least two different known forces")
    mean_x = statistics.mean(point["mean_counts"] for point in points)
    mean_y = statistics.mean(point["known_force_N"] for point in points)
    xx = sum((point["mean_counts"] - mean_x) ** 2 for point in points)
    xy = sum((point["mean_counts"] - mean_x) * (point["known_force_N"] - mean_y)
             for point in points)
    slope = xy / xx if xx else 0
    if xx < 10000 or not math.isfinite(slope) or abs(slope) < 1e-15:
        raise ValueError("Insufficient load variation or invalid calibration points (firmware fit limits)")
    tare = mean_x - mean_y / slope
    if not math.isfinite(tare):
        raise ValueError("Calibration produced a non-finite tare")
    fitted = []
    for point in points:
        predicted = (point["mean_counts"] - tare) * slope
        fitted.append(dict(point, fitted_force_N=predicted,
                           residual_N=predicted - point["known_force_N"]))
    return {"equation": "force_N = (force_raw - tare_counts) * newtons_per_count",
            "tare_counts": tare, "newtons_per_count": slope, "points": fitted}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--point", action="append", nargs="+", required=True,
                        metavar="VALUE", help="NEWTONS CSV [START_S END_S]; repeat for each known load")
    parser.add_argument("--output", type=Path, help="Save coefficients and point statistics as JSON")
    args = parser.parse_args(argv)
    try:
        points = []
        for spec in args.point:
            if len(spec) not in (2, 4):
                raise ValueError("Each --point needs NEWTONS CSV or NEWTONS CSV START_S END_S")
            force = finite_number(spec[0])
            start, end = (None, None)
            if len(spec) == 4:
                start, end = map(finite_number, spec[2:])
                if start < 0 or end <= start:
                    raise ValueError("Point timestamps must satisfy 0 <= START_S < END_S")
            points.append(read_point(spec[1], force, start, end))
        result = fit_calibration(points)
        if args.output:
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump(result, stream, indent=2, allow_nan=False)
                stream.write("\n")
    except (OSError, ValueError, OverflowError, csv.Error) as error:
        parser.error(str(error))
    print(result["equation"])
    print(f"tare_counts = {result['tare_counts']:.9g}")
    print(f"newtons_per_count = {result['newtons_per_count']:.9g}")
    for index, point in enumerate(result["points"], 1):
        print(f"Point {index}: {point['known_force_N']:.6g} N, n={point['samples']}, "
              f"mean={point['mean_counts']:.6f}, std={point['std_counts']:.6f} counts, "
              f"residual={point['residual_N']:.6g} N, rejected={point['rejected_rows']}")
        if point["max_dropped_lines"]:
            print(f"Warning: {point['file']} reports cumulative dropped_lines="
                  f"{point['max_dropped_lines']} (may include earlier output)", file=sys.stderr)
    if args.output:
        print(f"Saved {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
