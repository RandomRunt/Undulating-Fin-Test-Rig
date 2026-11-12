"""Compare thruster/fin force and fin-attached/detached electrical power.

Run: python software/PlotFinalTests.py
Saves thesis figures (600 dpi PNG and SVG), captions and numerical summaries.
"""

import csv
import hashlib
import json
import math
from pathlib import Path
import re
import statistics

from PlotRecording import read_recording
from final_test_figures import make_plots, write_captions


INPUT = Path(__file__).resolve().parents[1] / "recordings" / "Tests Final"
OUTPUT = INPUT / "plots"
GROUPS = (
    ("Thruster", "#0072B2", "o"),
    ("Undulating fin", "#D55E00", "s"),
    ("Undulating mechanism without fin", "#009E73", "^"),
)
PWM_STEP = re.compile(r"^PWM step (\d+)/20: nominal (\d+) W, PWM (\d+) us; hold 30 s\.$", re.M)


def summarise_run(path, index):
    """Keep paired force/power readings and summarise each recorded setting."""
    samples, malformed, dropped = read_recording(path)
    if malformed or dropped:
        raise ValueError(f"{path.name}: malformed={malformed}, dropped={dropped}")
    if any(b["time_s"] <= a["time_s"] for a, b in zip(samples, samples[1:])):
        raise ValueError(f"{path.name}: timestamps are not strictly increasing")
    is_power_test = index <= 10
    completion = "Power test complete." if is_power_test else "PWM test complete."
    transcript = path.read_text(encoding="utf-8-sig")
    if transcript.count(completion) != 1:
        raise ValueError(f"{path.name}: expected exactly one completed test")
    pwm_steps = [tuple(map(int, match)) for match in PWM_STEP.findall(transcript)]
    if not is_power_test and (
            len(pwm_steps) != 20 or
            [(step, nominal) for step, nominal, _ in pwm_steps] !=
            [(step, step) for step in range(1, 21)]):
        raise ValueError(f"{path.name}: expected PWM steps labelled 1-20 nominal W")
    group = GROUPS[(index - 1) // 5][0]
    blocks = {}
    start = None
    previous_key = None
    for sample in samples:
        if is_power_test:
            if not math.isfinite(sample["test_step"]):
                raise ValueError(f"{path.name}: missing power-test step")
            key = int(sample["test_step"])
            if sample["target_power_W"] != key:
                raise ValueError(f"{path.name}: unexpected power target")
        else:
            key = sample["pwm_us"]
        if key != previous_key:
            if key in blocks:
                raise ValueError(f"{path.name}: repeated setting block")
            start = sample["time_s"]
            blocks[key] = []
            previous_key = key
        selected = (sample["power_settled"] is True if is_power_test else
                    sample["time_s"] - start >= 5.0 - 1e-9)
        if selected and all(math.isfinite(sample[k]) for k in ("force_N", "power_W")):
            blocks[key].append(sample)
    if len(blocks) != 20 or any(not rows for rows in blocks.values()):
        raise ValueError(f"{path.name}: expected 20 populated settings")
    if is_power_test and list(blocks) != list(range(1, 21)):
        raise ValueError(f"{path.name}: expected power targets 1-20 W in order")
    if not is_power_test and list(blocks) != [pwm for _, _, pwm in pwm_steps]:
        raise ValueError(f"{path.name}: measured PWM blocks differ from the step table")
    records = []
    for step, (key, rows) in enumerate(blocks.items(), 1):
        forces = [r["force_N"] for r in rows]
        powers = [r["power_W"] for r in rows]
        if statistics.mean(powers) <= 0:
            raise ValueError(f"{path.name}: non-positive mean power at step {step}")
        records.append(dict(
            test_number=index, configuration=group, run=(index - 1) % 5 + 1,
            recording=path.name, step=step,
            target_power_W=key if is_power_test else "",
            reference_fin_target_power_W=step if index > 5 else "",
            mean_pwm_us=statistics.mean(r["pwm_us"] for r in rows),
            selected_samples=len(rows),
            mean_power_W=statistics.mean(powers),
            mean_force_N=statistics.mean(forces),
            force_per_watt_N_W=statistics.mean(forces) / statistics.mean(powers),
            within_step_force_SD_N=statistics.stdev(forces),
            within_step_power_SD_W=statistics.stdev(powers)))
    metadata = dict(
        test_number=index, configuration=group, run=(index - 1) % 5 + 1,
        recording=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        total_samples=len(samples), selected_samples=sum(len(r) for r in blocks.values()),
        settings=20, selection="Settled=1" if is_power_test else "Exclude first 5 s per PWM step")
    return records, metadata


def configuration_means(records):
    """Average five run means equally at corresponding settings within a group."""
    means = []
    for label, _, _ in GROUPS:
        for step in range(1, 21):
            rows = [r for r in records if r["configuration"] == label and r["step"] == step]
            if len(rows) != 5:
                raise ValueError(f"Expected five runs for {label}, step {step}")
            means.append(dict(
                configuration=label, step=step, runs=5,
                target_power_W=rows[0]["target_power_W"],
                reference_fin_target_power_W=rows[0]["reference_fin_target_power_W"],
                mean_pwm_us=statistics.mean(r["mean_pwm_us"] for r in rows),
                mean_power_W=statistics.mean(r["mean_power_W"] for r in rows),
                mean_force_N=statistics.mean(r["mean_force_N"] for r in rows),
                mean_run_force_per_watt_N_W=statistics.mean(r["force_per_watt_N_W"] for r in rows),
                between_run_force_per_watt_SD_N_W=statistics.stdev(r["force_per_watt_N_W"] for r in rows),
                between_run_force_SD_N=statistics.stdev(r["mean_force_N"] for r in rows),
                between_run_power_SD_W=statistics.stdev(r["mean_power_W"] for r in rows)))
    return means


def fin_power_comparison(records, means):
    """Match the two five-run groups by the fin-referenced PWM table step.

    The groups are treated as unpaired repeats. Keep measured PWM
    differences visible rather than interpolating or equating their power.
    """
    comparison = []
    for step in range(1, 21):
        attached = next(r for r in means if r["configuration"] == GROUPS[1][0]
                        and r["step"] == step)
        detached = next(r for r in means if r["configuration"] == GROUPS[2][0]
                        and r["step"] == step)
        commands = {r["mean_pwm_us"] for r in records
                    if r["configuration"] == GROUPS[2][0] and r["step"] == step}
        if len(commands) != 1:
            raise ValueError(f"No-fin runs use different PWM commands at step {step}")
        difference = attached["mean_power_W"] - detached["mean_power_W"]
        comparison.append(dict(
            step=step, reference_fin_target_power_W=step,
            fin_attached_runs=5, fin_removed_runs=5,
            fin_attached_mean_pwm_us=attached["mean_pwm_us"],
            fin_removed_pwm_us=detached["mean_pwm_us"],
            removed_minus_attached_pwm_us=detached["mean_pwm_us"] - attached["mean_pwm_us"],
            fin_attached_mean_power_W=attached["mean_power_W"],
            fin_removed_mean_power_W=detached["mean_power_W"],
            fin_attached_between_run_power_SD_W=attached["between_run_power_SD_W"],
            fin_removed_between_run_power_SD_W=detached["between_run_power_SD_W"],
            attached_minus_removed_power_W=difference,
            power_difference_SE_W=math.sqrt(
                attached["between_run_power_SD_W"] ** 2 / attached["runs"] +
                detached["between_run_power_SD_W"] ** 2 / detached["runs"]),
            power_reduction_percent=100 * difference / attached["mean_power_W"]))
    return comparison


def write_csv(name, records):
    with (OUTPUT / name).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def main():
    paths = sorted(INPUT.glob("*.log"))
    if len(paths) != 15:
        raise ValueError(f"Expected 15 source logs in {INPUT}; found {len(paths)}")
    records, sources = [], []
    for index, path in enumerate(paths, 1):
        run_records, metadata = summarise_run(path, index)
        records.extend(run_records)
        sources.append(metadata)
    means = configuration_means(records)
    comparison = fin_power_comparison(records, means)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    make_plots(records, means, comparison, GROUPS, OUTPUT)
    write_captions(OUTPUT)
    write_csv("per_test_step_means.csv", records)
    write_csv("configuration_step_averages.csv", means)
    write_csv("fin_power_comparison.csv", comparison)
    (OUTPUT / "sources.json").write_text(json.dumps(sources, indent=2) + "\n", encoding="utf-8")
    mapping = "\n".join(f"| {s['test_number']} | {s['configuration']} | {s['recording']} |" for s in sources)
    (OUTPUT / "method.md").write_text(
        "# Final-test analysis method\n\n"
        "The 15 source logs directly in Tests Final are sorted by filename timestamp. "
        "Tests 1-5 are thruster, 6-10 fin attached, and 11-15 mechanism without fin. "
        "Source logs are read only; sources.json records SHA-256 hashes and selection counts.\n\n"
        "## Selection and repeated units\n\n"
        "Power-controlled tests retain all finite force/power pairs flagged Settled=1. "
        "The flag describes electrical regulation, not demonstrated force settling. "
        "No-fin tests exclude the first 5 s of each 30 s PWM hold as a fixed transient allowance. "
        "Steps 1-20 and the PWM block order are validated. Signed force is retained without "
        "offset correction or magnitude conversion. No data are smoothed, and no point is "
        "removed as an outlier. The repeated unit is a run: n=5 per configuration, not the "
        "number of time-correlated samples in a hold. The same run visits all 20 steps, so "
        "steps are not independent experimental replicates.\n\n"
        "## Means, dispersion and derived quantities\n\n"
        "Each run is reduced to its arithmetic mean force, power and PWM at each setting. "
        "Configuration means equally weight the five run means. Sample SD uses n-1=4. "
        "Averaged force plots show horizontal power SD and vertical force SD. Averaged "
        "power plots show power SD. These describe between-run spread, not confidence "
        "intervals or complete measurement uncertainty.\n\n"
        "At each step the attached-minus-removed power difference is the difference of the "
        "two group means. Its standard error is sqrt(s_attached^2/5 + s_removed^2/5), "
        "assuming independent run means between groups. The plot shows +/-1 SE, without "
        "claiming a coverage probability. The groups were recorded in separate sessions; "
        "session effects cannot be separated from configuration effects in this dataset. "
        "Shared calibration/systematic effects are not represented in this SE.\n\n"
        "Force per watt is computed within each run as mean signed force / mean measured "
        "electrical power using the same paired samples. The plotted configuration value "
        "is the mean of the five run ratios; its SD is calculated directly from those "
        "ratios, retaining the observed association of force and power across runs. It is not "
        "a mean of instantaneous sample ratios, a ratio of grand means, or a dimensionless "
        "propulsive efficiency. No mechanism baseline is subtracted from the denominator.\n\n"
        "## Alignment and interpretation\n\n"
        "Thruster/fin force comparisons contain only the ten power-controlled runs. "
        "Means are aligned within each group by nominal target, but plotted against "
        "measured power: equal target labels do not guarantee equal measured power. "
        "Fin/no-fin power comparisons contain only the corresponding ten runs and use "
        "fin-attached reference targets as x coordinates. These 1-20 W labels identify "
        "the PWM table steps, not measured no-fin watts. No-fin PWM is constant across "
        "the five repeats at each step. "
        f"Maximum absolute difference from the fin group's mean PWM is {max(abs(r['removed_minus_attached_pwm_us']) for r in comparison):.3f} us. "
        "Matched PWM does not establish matched motor speed or fin kinematics. "
        "No interpolation, extrapolation or fitted performance model is used. Connecting "
        "lines are visual guides. Electrical differences are not labelled hydrodynamic "
        "power or isolated mechanical loss.\n\n"
        "## Figures and numerical outputs\n\n"
        "Five figures are saved as 600 dpi PNG and editable SVG, at 180 mm width. "
        "figure_captions.md supplies thesis-ready captions, selection rules and statistical "
        "limitations for each figure. The first four figures replace the earlier versions; "
        "force_per_watt is added for the static electrical-performance comparison. "
        "per_test_step_means.csv contains 300 per-run points; configuration_step_averages.csv "
        "contains 60 means and SDs; fin_power_comparison.csv contains 20 differences, their "
        "SEs, power changes and PWM alignment. Within-step SDs and between-run SDs are "
        "separately named. The original combined all_15_tests figure is superseded.\n\n"
        "## Measurement uncertainty\n\n"
        "Run-to-run dispersion is a partial characterisation of repeatability. No force "
        "or power calibration uncertainty specification is provided to this script. "
        "A complete uncertainty budget, including calibration, drift and alignment, "
        "must be established separately before claiming absolute accuracy. See "
        "[NIST TN 1297](https://www.nist.gov/pml/nist-technical-note-1297/nist-tn-1297-appendix-law-propagation-uncertainty) "
        "for the statistical mean and uncertainty-propagation conventions.\n\n"
        "| Test | Configuration | Recording |\n| --- | --- | --- |\n" + mapping + "\n",
        encoding="utf-8")
    for path, source in zip(paths, sources):
        if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError(f"Source changed during analysis: {path}")
    # Retire the superseded combined graph after the replacement outputs succeed.
    for name in ("all_15_tests.png", "all_15_tests.svg"):
        (OUTPUT / name).unlink(missing_ok=True)
    print(f"Saved five thesis figures (600 dpi PNG + SVG), {len(records)} per-test points, "
          f"{len(means)} average points and {len(comparison)} power-comparison steps to {OUTPUT}")
    for source in sources:
        print(f"{source['test_number']:02d} {source['configuration']}: "
              f"{source['selected_samples']}/{source['total_samples']} samples selected")


if __name__ == "__main__":
    main()
