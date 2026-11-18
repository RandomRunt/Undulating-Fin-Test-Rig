"""Extract the latest fitted calibration; run from the repository root:
python software/LoadCellCalibration.py software/recordings/run.log --output software/recordings/calibration.json
--plot shows calibration quality; repeat --point NEWTONS CSV to fit known loads.
Use the saved JSON with PlotRecording.py --calibration for experimental graphs.
"""

import argparse
import csv
import json
import math
from pathlib import Path
import re
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


def read_log(path, session=None):
    """Select a completed firmware fit without refitting rounded point summaries."""
    points = []
    sessions = []
    active = None
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        point = re.search(r"Point (\d+): force=(\S+) N, mean_raw=(\S+) counts", line)
        fit = re.search(r"Calibration fitted: tare_counts=([^,\s]+), newtons_per_count=(\S+)", line)
        residual = re.search(r"Point (\d+) residual: (\S+) N", line)
        if "ESC is neutral. Apply calibration forces" in line:
            points = []
            active = None
        if point:
            index = int(point[1])
            if index == 1:
                points = []
            active = None
            if index != len(points) + 1:
                raise ValueError(f"{path}:{line_number}: missing or out-of-order calibration point")
            points.append({"known_force_N": finite_number(point[2]),
                           "mean_counts": finite_number(point[3])})
        elif fit:
            tare, scale = finite_number(fit[1]), finite_number(fit[2])
            if scale == 0:
                raise ValueError(f"{path}:{line_number}: calibration scale cannot be zero")
            fitted = []
            for item in points:
                predicted = (item["mean_counts"] - tare) * scale
                fitted.append(dict(item, fitted_force_N=predicted,
                                   residual_N=predicted - item["known_force_N"],
                                   residual_source="rounded point summary"))
            active = {
                "equation": "force_N = (force_raw - tare_counts) * newtons_per_count",
                "tare_counts": tare, "newtons_per_count": scale, "points": fitted,
                "source": "firmware fit", "file": str(path), "fit_line": line_number,
                "session": len(sessions) + 1,
            }
            sessions.append(active)
        elif residual and active is not None:
            index = int(residual[1]) - 1
            if 0 <= index < len(active["points"]):
                active["points"][index]["residual_N"] = finite_number(residual[2])
                active["points"][index]["residual_source"] = "firmware"
    if not sessions:
        raise ValueError(f"{path}: no completed 'Calibration fitted:' entry found; run firmware fit first")
    if session is not None and not 1 <= session <= len(sessions):
        raise ValueError(f"--session must be between 1 and {len(sessions)}")
    result = sessions[-1 if session is None else session - 1]
    result["sessions_found"] = len(sessions)
    return result


def plot_calibration(result, show=False, save=None):
    if not result["points"]:
        raise ValueError("The log contains coefficients but no calibration points to plot")
    if not show:
        import matplotlib
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    points = sorted(result["points"], key=lambda point: point["mean_counts"])
    counts = [point["mean_counts"] for point in points]
    forces = [point["known_force_N"] for point in points]
    fitted = [(count - result["tare_counts"]) * result["newtons_per_count"] for count in counts]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    axes[0].scatter(counts, forces, label="Known loads")
    axes[0].plot(counts, fitted, label="Calibration fit")
    axes[0].set(xlabel="Mean raw counts", ylabel="Force (N)", title="Load-cell calibration")
    axes[0].legend()
    axes[1].scatter(forces, [point["residual_N"] for point in points])
    axes[1].axhline(0, color="gray", linewidth=1)
    axes[1].set(xlabel="Known force (N)", ylabel="Fitted − known force (N)", title="Residual error")
    for axis in axes:
        axis.grid(alpha=0.25)
    try:
        if save:
            fig.savefig(save, dpi=160)
        if show:
            plt.show()
    finally:
        plt.close(fig)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log", type=Path, nargs="?", help="Terminal log containing firmware calibration fits")
    parser.add_argument("--point", action="append", nargs="+",
                        metavar="VALUE", help="NEWTONS CSV [START_S END_S]; repeat for each known load")
    parser.add_argument("--output", type=Path, help="Save coefficients and point statistics as JSON")
    parser.add_argument("--session", type=int, help="Completed fit number in log (1-based; default: latest)")
    parser.add_argument("--plot", action="store_true", help="Display calibration and residual plots")
    parser.add_argument("--save-plot", type=Path, help="Save plots to an image without requiring a window")
    args = parser.parse_args(argv)
    if bool(args.log) == bool(args.point):
        parser.error("Supply either a terminal log or --point arguments")
    if args.session is not None and args.log is None:
        parser.error("--session requires a terminal log")
    try:
        points = []
        for spec in args.point or []:
            if len(spec) not in (2, 4):
                raise ValueError("Each --point needs NEWTONS CSV or NEWTONS CSV START_S END_S")
            force = finite_number(spec[0])
            start, end = (None, None)
            if len(spec) == 4:
                start, end = map(finite_number, spec[2:])
                if start < 0 or end <= start:
                    raise ValueError("Point timestamps must satisfy 0 <= START_S < END_S")
            points.append(read_point(spec[1], force, start, end))
        result = read_log(args.log, args.session) if args.log else fit_calibration(points)
        if args.output and args.output.exists():
            raise ValueError(f"{args.output} already exists; choose a new output path")
        if args.plot or args.save_plot:
            plot_calibration(result, args.plot, args.save_plot)
        if args.output:
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump(result, stream, indent=2, allow_nan=False)
                stream.write("\n")
    except (OSError, ValueError, OverflowError, csv.Error, ImportError) as error:
        parser.error(str(error))
    if args.log:
        print(f"Using completed fit {result['session']} of {result['sessions_found']} "
              f"(line {result['fit_line']}); preserving firmware coefficients.")
    print(result["equation"])
    print(f"tare_counts = {result['tare_counts']:.15g}")
    print(f"newtons_per_count = {result['newtons_per_count']:.9g}")
    for index, point in enumerate(result["points"], 1):
        if args.log:
            print(f"Point {index}: {point['known_force_N']:.6g} N, "
                  f"mean={point['mean_counts']:.3f} counts, "
                  f"residual={point['residual_N']:.6g} N ({point['residual_source']})")
            continue
        print(f"Point {index}: {point['known_force_N']:.6g} N, n={point['samples']}, "
              f"mean={point['mean_counts']:.6f}, std={point['std_counts']:.6f} counts, "
              f"residual={point['residual_N']:.6g} N, rejected={point['rejected_rows']}")
        if point["max_dropped_lines"]:
            print(f"Warning: {point['file']} reports cumulative dropped_lines="
                  f"{point['max_dropped_lines']} (may include earlier output)", file=sys.stderr)
    if args.output:
        print(f"Saved {args.output}")
    if args.save_plot:
        print(f"Saved {args.save_plot}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
