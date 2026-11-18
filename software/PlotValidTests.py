"""Plot FIN and THRUST recordings as four-panel figures.

Run from any directory:
    python software/PlotValidTests.py
    python software/PlotValidTests.py --no-show

Requires Matplotlib. Defaults to recordings/Valid Tests and saves PNG figures
and per-target summary CSVs in recordings/Valid Tests/plots. Existing outputs
with the same names are replaced. Recorded forces retain their sign and units.
"""

import argparse
import csv
import math
from pathlib import Path
import re
import statistics

from PlotRecording import read_recording


DEFAULT_INPUT = Path(__file__).resolve().parents[1] / "recordings" / "Valid Tests"


def recording_kind(path):
    """Match filename tokens, so FIN does not also match e.g. 'unfinished'."""
    tokens = re.split(r"[^a-z0-9]+", path.stem.lower())
    return next((kind for kind in ("fin", "thrust") if kind in tokens), None)


def group_by_target(samples, include_unsettled=False):
    """Keep paired finite measurements; group by target, not noisy actual watts."""
    groups = {}
    for row in samples:
        if not all(math.isfinite(row[key]) for key in
                   ("target_power_W", "force_N", "power_W")):
            continue
        if not include_unsettled and row["power_settled"] is not True:
            continue
        groups.setdefault(row["target_power_W"], []).append(row)
    return dict(sorted(groups.items()))


def time_blocks(samples):
    """Break lines at transcript boundaries or clock resets; start time at zero."""
    blocks = []
    origin = samples[0]["time_s"]
    for row in samples:
        if (not blocks or row["boundary"] or
                row["time_s"] <= blocks[-1][-1]["time_s"]):
            blocks.append([])
        blocks[-1].append(row)
    return origin, blocks


def plot_tests(samples, groups, kind, filename, include_unsettled=False):
    import matplotlib.pyplot as plt

    color = {"fin": "#007C91", "thrust": "#B34E00"}[kind]
    selection = "All valid readings" if include_unsettled else "Settled readings only"
    fig, axes = plt.subplots(2, 2, figsize=(15, 10), layout="constrained")
    power_ax, force_ax, relation_ax, box_ax = axes.flat
    origin, blocks = time_blocks(samples)
    for i, block in enumerate(blocks):
        times = [row["time_s"] - origin for row in block]
        power_ax.plot(times, [row["power_W"] for row in block],
                      color=color, linewidth=0.8, label="Measured" if i == 0 else None)
        power_ax.plot(times, [row["target_power_W"] for row in block],
                      color="#333333", linestyle="--", linewidth=1.1,
                      label="Target" if i == 0 else None)
        force_ax.plot(times, [row["force_N"] for row in block],
                      color=color, linewidth=0.7)

    power_ax.set(title="Power over time", xlabel="Time since first sample (s)",
                 ylabel="Electrical power (W)")
    power_ax.legend()
    force_ax.set(title="Force over time", xlabel="Time since first sample (s)",
                 ylabel="Force (N)")

    rows = [row for group in groups.values() for row in group]
    relation_ax.scatter([row["power_W"] for row in rows],
                        [row["force_N"] for row in rows],
                        s=5, alpha=0.16, color=color, edgecolors="none",
                        label="Individual readings", rasterized=True)
    relation_ax.plot([statistics.mean(row["power_W"] for row in group)
                      for group in groups.values()],
                     [statistics.mean(row["force_N"] for row in group)
                      for group in groups.values()],
                     "o-", color="#222222", markersize=4, linewidth=1.2,
                     label="Mean at each target")
    relation_ax.set(title=f"Force vs power — {selection.lower()}",
                    xlabel="Measured electrical power (W)", ylabel="Force (N)")
    relation_ax.legend()

    targets = list(groups)
    spacing = min((b - a for a, b in zip(targets, targets[1:])), default=1.0)
    boxes = box_ax.boxplot(
        [[row["force_N"] for row in group] for group in groups.values()],
        positions=targets, widths=0.6 * spacing, patch_artist=True,
        showmeans=True,
        medianprops={"color": "#222222", "linewidth": 1.3},
        meanprops={"marker": "D", "markerfacecolor": "white",
                   "markeredgecolor": "#222222", "markersize": 3},
        flierprops={"marker": ".", "markersize": 2, "alpha": 0.35,
                    "markeredgecolor": color})
    for box in boxes["boxes"]:
        box.set(facecolor=color, alpha=0.45)
    box_ax.set_xticks(targets, [f"{target:g}" for target in targets])
    box_ax.set(title=f"Force by power level — {selection.lower()}",
               xlabel="Target electrical power (W)", ylabel="Force (N)")
    box_ax.text(0.02, 0.98, "Box: middle 50% • line: median • diamond: mean\n"
                "Whiskers: within 1.5 × IQR • dots: outliers",
                transform=box_ax.transAxes, va="top", fontsize=8,
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.85})
    for ax in axes.flat:
        ax.grid(True, alpha=0.2)
        ax.set_axisbelow(True)
    fig.suptitle(f"{kind.upper()} recordings\n{filename}", fontsize=14)
    return fig


def write_summary(path, groups):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("target_power_W", "samples", "mean_power_W", "mean_force_N",
                         "median_force_N", "std_force_N", "min_force_N", "max_force_N"))
        for target, rows in groups.items():
            forces = [row["force_N"] for row in rows]
            writer.writerow((target, len(rows),
                             statistics.mean(row["power_W"] for row in rows),
                             statistics.mean(forces), statistics.median(forces),
                             statistics.stdev(forces) if len(forces) > 1 else "",
                             min(forces), max(forces)))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT,
                        help="Directory containing FIN/THRUST .log or .csv files")
    parser.add_argument("--output-dir", type=Path,
                        help="Output directory (default: <input-dir>/plots)")
    parser.add_argument("--include-unsettled", action="store_true",
                        help="Include transient readings in force-power and box plots")
    parser.add_argument("--no-show", action="store_true",
                        help="Save figures without opening interactive windows")
    args = parser.parse_args(argv)
    try:
        if not args.input_dir.is_dir():
            raise ValueError(f"Recording directory does not exist: {args.input_dir}")
        paths = sorted(path for path in args.input_dir.iterdir()
                       if path.is_file() and path.suffix.lower() in (".log", ".csv")
                       and recording_kind(path))
        if not paths:
            raise ValueError(f"No FIN/THRUST .log or .csv recordings in {args.input_dir}")
        if args.no_show:
            import matplotlib
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        output = args.output_dir or args.input_dir / "plots"
        output.mkdir(parents=True, exist_ok=True)
        for path in paths:
            samples, malformed, dropped = read_recording(path)
            groups = group_by_target(samples, args.include_unsettled)
            if not groups:
                raise ValueError(f"{path.name}: no paired force (N) / power (W) readings "
                                 "with target watts matching the selected settling filter")
            kind = recording_kind(path)
            fig = plot_tests(samples, groups, kind, path.name, args.include_unsettled)
            # Retain the source extension to avoid collisions between a CSV and log.
            stem = output / path.name
            image_path = stem.with_name(stem.name + "_plots.png")
            csv_path = stem.with_name(stem.name + "_summary.csv")
            fig.savefig(image_path, dpi=180)
            write_summary(csv_path, groups)
            print(f"{kind.upper()}: {len(samples):,} total samples; "
                  f"{sum(map(len, groups.values())):,} selected pairs; "
                  f"{len(groups)} target levels ({min(groups):g}–{max(groups):g} W)")
            print(f"  Figure: {image_path}\n  Summary: {csv_path}")
            if malformed or dropped:
                print(f"  Warning: malformed rows={malformed}; "
                      f"max cumulative dropped_lines={dropped}")
            if args.no_show:
                plt.close(fig)
        print("Time plots include transients. Box groups use target watts; "
              "force-power x values use measured watts. Force signs are preserved.")
        if not args.no_show:
            plt.show()
        plt.close("all")
    except (OSError, ValueError, ImportError, csv.Error) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
