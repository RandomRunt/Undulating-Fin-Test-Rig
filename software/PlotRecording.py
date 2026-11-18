"""Plot test CSV/log measurements; run from the repository root:
python software/PlotRecording.py software/recordings/run.log --calibration software/recordings/calibration.json
Omit --calibration if already calibrated; --save plot.png exports the figure.
Power tests summarise settled rows by target watts; other tests group by PWM.
"""

import argparse
import csv
import json
import math
from pathlib import Path
import re
import statistics
import sys


FORMATTED = re.compile(
    r"^Timestamp: (\d+) us, Force: (.*?), Voltage: (\S+) V, "
    r"Current: (\S+) A, Power: (\S+) W, Current PWM: (\d+) us"
    r"(?:, Target: (\S+) W, Filtered: (\S+) W, Settled: ([01]), Step: (\d+))?$"
)
FIELDS = {"time_us", "force_raw", "force_N", "voltage_V", "current_A",
          "power_W", "pulse_us", "power_status", "force_status"}


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else math.nan
    except (ValueError, TypeError):
        return math.nan


def read_recording(path, calibration=None):
    """Read mixed CSV/formatted output; retain gaps as NaNs in time plots."""
    samples = []
    header = None
    boundary = True
    malformed = 0
    dropped = 0
    with Path(path).open(encoding="utf-8-sig") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            if line.startswith("time_us,"):
                header = next(csv.reader([line]))
                if not FIELDS.issubset(header) or len(header) != len(set(header)):
                    raise ValueError("Unsupported Thesis-DAQ CSV header")
                boundary = True
                continue
            match = FORMATTED.fullmatch(line)
            target = filtered = None
            settled = None
            test_step = math.nan
            if match:
                timestamp, force, voltage, current, power, pwm, target, filtered, settled, test_step = match.groups()
                raw = number(force.split(" counts")[0]) if " counts" in force else math.nan
                force_N = number(force[:-2]) if force.endswith(" N") else math.nan
            elif header and re.match(r"^\d+,", line):
                row = next(csv.reader([line]))
                if len(row) != len(header):
                    malformed += 1
                    boundary = True
                    continue
                record = dict(zip(header, row))
                target = record.get("target_power_W")
                filtered = record.get("filtered_power_W")
                settled = record.get("power_settled")
                test_step = record.get("test_step")
                timestamp, pwm = record["time_us"], record["pulse_us"]
                raw = number(record["force_raw"])
                force_N = number(record["force_N"])
                if record["force_status"] != "ESP_OK":
                    raw = force_N = math.nan
                voltage, current, power = (record[k] for k in
                                           ("voltage_V", "current_A", "power_W"))
                if record["power_status"] != "ESP_OK":
                    voltage = current = power = math.nan
                lost = number(record.get("dropped_lines", "0"))
                if math.isfinite(lost):
                    dropped = max(dropped, int(lost))
            else:
                # Commands, menus and test completion separate recording blocks.
                boundary = True
                continue
            timestamp, pwm = number(timestamp), number(pwm)
            if target is not None:
                if (not math.isfinite(number(target)) or number(target) <= 0 or
                        settled not in ("0", "1") or not math.isfinite(number(test_step)) or
                        number(test_step) < 1 or not number(test_step).is_integer()):
                    malformed += 1
                    boundary = True
                    continue
            if not math.isfinite(timestamp) or timestamp < 0 or not math.isfinite(pwm):
                malformed += 1
                boundary = True
                continue
            if calibration and math.isfinite(raw):
                force_N = (raw - calibration["tare_counts"]) * calibration["newtons_per_count"]
            samples.append(dict(time_s=timestamp / 1e6, pwm_us=int(pwm),
                                force_raw=raw, force_N=force_N,
                                voltage_V=number(voltage), current_A=number(current),
                                power_W=number(power), boundary=boundary,
                                target_power_W=number(target), filtered_power_W=number(filtered),
                                power_settled=settled == "1" if settled is not None else None,
                                test_step=number(test_step)))
            boundary = False
    if not samples:
        raise ValueError("No Thesis-DAQ samples found in the selected recording")
    return samples, malformed, dropped


def summarise(samples, settle_seconds=1.0, min_power=0.01):
    """Group power tests by target and settled flag; other tests by PWM command."""
    groups = {}
    step_start = None
    previous = None
    for sample in samples:
        target = sample.get("target_power_W", math.nan)
        power_test = math.isfinite(target)
        key = ("power", target) if power_test else ("pwm", sample["pwm_us"])
        previous_target = previous.get("target_power_W", math.nan) if previous else math.nan
        previous_key = (("power", previous_target) if math.isfinite(previous_target)
                        else ("pwm", previous["pwm_us"])) if previous else None
        if (previous is None or sample["boundary"] or
                key != previous_key or
                (power_test and sample.get("test_step") != previous.get("test_step")) or
                sample["time_s"] <= previous["time_s"]):
            step_start = sample["time_s"]
        previous = sample
        if sample["time_s"] - step_start < settle_seconds:
            continue
        if power_test and sample.get("power_settled") is not True:
            continue
        groups.setdefault(key, []).append(sample)
    result = []
    for (kind, setting), rows in sorted(groups.items()):
        def mean(key):
            values = [row[key] for row in rows if math.isfinite(row[key])]
            return statistics.mean(values) if values else math.nan
        paired = [row for row in rows if math.isfinite(row["force_N"]) and
                  math.isfinite(row["power_W"]) and row["power_W"] > min_power]
        force = statistics.mean(row["force_N"] for row in paired) if paired else math.nan
        power = statistics.mean(row["power_W"] for row in paired) if paired else math.nan
        result.append(dict(pwm_us=mean("pwm_us") if kind == "power" else setting,
                           target_power_W=setting if kind == "power" else math.nan,
                           samples=len(rows), paired_samples=len(paired),
                           mean_force_N=mean("force_N"), mean_power_W=mean("power_W"),
                           mean_current_A=mean("current_A"),
                           force_per_watt_N_W=force / power if paired else math.nan))
    return result


def plot_recording(samples, summary, title):
    import matplotlib.pyplot as plt

    calibrated = any(math.isfinite(row["force_N"]) for row in samples)
    force_key = "force_N" if calibrated else "force_raw"
    fig, axes = plt.subplots(3, 2, figsize=(13, 10), constrained_layout=True)
    # Separate blocks and reboots rather than joining unrelated samples.
    blocks = []
    for sample in samples:
        if not blocks or sample["boundary"] or sample["time_s"] <= blocks[-1][-1]["time_s"]:
            blocks.append([])
        blocks[-1].append(sample)
    for block in blocks:
        t = [row["time_s"] for row in block]
        for ax, key in ((axes[0, 0], force_key), (axes[0, 1], "power_W"),
                        (axes[1, 0], "current_A"), (axes[1, 1], "pwm_us")):
            ax.plot(t, [row[key] for row in block], linewidth=1)
        if any(math.isfinite(row.get("target_power_W", math.nan)) for row in block):
            axes[0, 1].plot(t, [row["target_power_W"] for row in block], "--", linewidth=1,
                            color="black", label="Target power")
    handles, labels = axes[0, 1].get_legend_handles_labels()
    if handles:
        axes[0, 1].legend(handles[:1], labels[:1])
    for ax, label in zip(axes.flat[:4],
                         ("Force (N)" if calibrated else "Force (uncalibrated counts)",
                          "Electrical power (W)", "Supply current (A)", "PWM command (µs)")):
        ax.set(xlabel="Device time since boot (s)", ylabel=label)
    power_summary = [row for row in summary if math.isfinite(row["target_power_W"])]
    if power_summary:
        x = [row["mean_power_W"] for row in power_summary]
        axes[2, 0].plot(x, [row["mean_force_N"] for row in power_summary], "o-")
        axes[2, 0].set(xlabel="Mean electrical power (W)",
                       ylabel="Mean force (N)" if calibrated else "Mean force (N, uncalibrated)")
        axes[2, 1].plot(x, [row["force_per_watt_N_W"] for row in power_summary], "o-")
        axes[2, 1].set(xlabel="Mean electrical power (W)", ylabel="Signed force / power (N/W)")
    else:
        pwm = [row["pwm_us"] for row in summary]
        axes[2, 0].plot(pwm, [row["mean_power_W"] for row in summary], "o-")
        axes[2, 0].set(xlabel="PWM command (µs)", ylabel="Mean electrical power (W)")
        axes[2, 1].plot(pwm, [row["force_per_watt_N_W"] for row in summary], "o-")
        axes[2, 1].set(xlabel="PWM command (µs)", ylabel="Signed force / power (N/W)")
    if not calibrated:
        axes[2, 1].text(0.5, 0.5, "Requires calibrated force\nUse --calibration calibration.json",
                        ha="center", va="center", transform=axes[2, 1].transAxes)
    for ax in axes.flat:
        ax.grid(True, alpha=0.3)
    fig.suptitle(title + ("\nPower-test summaries use settled samples grouped by target watts"
                          if power_summary else
                          "\nPWM is a command, not measured RPM; summaries exclude settling"))
    return fig


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("recording", type=Path, nargs="?", help="CSV or terminal .log file")
    parser.add_argument("--calibration", type=Path, help="JSON from LoadCellCalibration.py")
    parser.add_argument("--settle-seconds", type=float, default=1.0,
                        help="Exclude seconds after each block/setting change (default: 1); power tests also require settled=1")
    parser.add_argument("--min-power", type=float, default=0.01,
                        help="Exclude power <= this value from N/W metrics (default: 0.01 W)")
    parser.add_argument("--save", type=Path, help="Save the plot, e.g. plots/run.png")
    parser.add_argument("--summary-csv", type=Path, help="Save the per-PWM or per-target-watt summary")
    parser.add_argument("--no-show", action="store_true", help="Skip the interactive plot window")
    args = parser.parse_args(argv)
    try:
        if args.recording is None:
            args.recording = Path(input("Recording .log or .csv path: ").strip().strip('"'))
        if not math.isfinite(args.settle_seconds) or args.settle_seconds < 0:
            raise ValueError("--settle-seconds must be finite and nonnegative")
        if not math.isfinite(args.min_power) or args.min_power < 0:
            raise ValueError("--min-power must be finite and nonnegative")
        calibration = None
        if args.calibration:
            calibration = json.loads(args.calibration.read_text(encoding="utf-8-sig"))
            for key in ("tare_counts", "newtons_per_count"):
                calibration[key] = float(calibration[key])
                if not math.isfinite(calibration[key]):
                    raise ValueError("Calibration coefficients must be finite")
            if calibration["newtons_per_count"] == 0:
                raise ValueError("Calibration scale must be nonzero")
        samples, malformed, dropped = read_recording(args.recording, calibration)
        summary = summarise(samples, args.settle_seconds, args.min_power)
        if not summary:
            raise ValueError("No settled samples; check --settle-seconds and power-test settled flags")
        if args.no_show:
            import matplotlib
            matplotlib.use("Agg")
        fig = plot_recording(samples, summary, args.recording.name)
        print("Target (W)  PWM (µs)  Samples  Paired  Force (N)  Power (W)  Current (A)  Force/W (N/W)")
        for row in summary:
            target = f"{row['target_power_W']:.3f}" if math.isfinite(row['target_power_W']) else "-"
            print(f"{target:>10}  {row['pwm_us']:8.1f}  {row['samples']:7}  {row['paired_samples']:6}  "
                  f"{row['mean_force_N']:9.4f}  {row['mean_power_W']:9.4f}  "
                  f"{row['mean_current_A']:11.4f}  {row['force_per_watt_N_W']:13.4f}")
        if not any(row["paired_samples"] for row in summary):
            print("N/W unavailable: requires calibrated force paired with positive valid power.")
        print("N/W = mean signed force / mean electrical power, using the same valid samples.")
        if malformed or dropped:
            print(f"Warning: skipped malformed rows={malformed}; max cumulative dropped_lines={dropped}.")
        if args.save:
            args.save.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(args.save, dpi=160)
            print(f"Saved plot: {args.save}")
        if args.summary_csv:
            args.summary_csv.parent.mkdir(parents=True, exist_ok=True)
            with args.summary_csv.open("x", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(summary[0]))
                writer.writeheader()
                writer.writerows({k: "" if isinstance(v, float) and not math.isfinite(v) else v
                                 for k, v in row.items()} for row in summary)
            print(f"Saved summary: {args.summary_csv}")
        import matplotlib.pyplot as plt
        if not args.no_show:
            plt.show()
        plt.close(fig)
    except (OSError, ValueError, KeyError, TypeError, csv.Error, ImportError, EOFError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    sys.exit(main())
