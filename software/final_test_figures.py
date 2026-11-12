"""Publication-sized descriptive figures for PlotFinalTests.py.

SD bars describe between-run spread. Difference bars describe the standard
error of the difference of independent group means, not instrument uncertainty.
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


LINESTYLES = ("-", "--", "-.", ":", (0, (5, 2, 1, 2)))
POWER_LABEL = r"Measured electrical power, $\overline{P}$ (W)"
FORCE_LABEL = r"Mean signed axial force, $\overline{F}$ (N)"
REFERENCE_LABEL = r"Fin-attached reference target power, $P_{\mathrm{ref}}$ (W)"
DISPLAY_NAMES = ("Thruster", "Undulating fin", "Mechanism without fin")


def style_axes(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(direction="out", width=0.7, length=3)
    ax.grid(True, which="major", color="0.87", linewidth=0.45)
    ax.set_axisbelow(True)
    ax.axhline(0, color="0.4", linewidth=0.65, zorder=1)


def power_axes(ax):
    style_axes(ax)
    ax.set(xlabel=POWER_LABEL, xlim=(0, 21), xticks=range(0, 22, 2))


def reference_axes(ax):
    style_axes(ax)
    ax.set(xlabel=REFERENCE_LABEL, xlim=(0, 21), xticks=[1, 5, 10, 15, 20])


def save_figure(fig, name, output):
    # Fixed page-width dimensions; no large titles or captions in the image.
    fig.savefig(output / (name + ".png"), dpi=600, facecolor="white")
    fig.savefig(output / (name + ".svg"), facecolor="white")
    plt.close(fig)


def step_rows(records, configuration):
    return sorted((r for r in records if r["configuration"] == configuration),
                  key=lambda r: r["step"])


def all_runs(records, groups, indices, xkey, output, name, force=False):
    fig, axes = plt.subplots(1, 2, figsize=(7.1, 3.9), sharex=True, sharey=True)
    fig.subplots_adjust(left=0.11, right=0.98, bottom=0.28, top=0.89, wspace=0.13)
    for panel, (ax, group_index) in enumerate(zip(axes, indices)):
        group, color, marker = groups[group_index]
        for run in range(1, 6):
            rows = sorted((r for r in records if r["configuration"] == group
                           and r["run"] == run), key=lambda r: r["step"])
            ax.plot([r[xkey] for r in rows],
                    [r["mean_force_N" if force else "mean_power_W"] for r in rows],
                    color=color, marker=marker, markersize=3, markerfacecolor="white",
                    markeredgewidth=0.7, linewidth=1, linestyle=LINESTYLES[run - 1])
        (power_axes if force else reference_axes)(ax)
        # Use a single common x label to retain readable labels at thesis width.
        ax.set_xlabel("")
        ax.set_title(f"({chr(97 + panel)}) {DISPLAY_NAMES[group_index]}", fontsize=10)
    axes[0].set_ylabel(FORCE_LABEL if force else POWER_LABEL)
    if not force:
        axes[0].set_ylim(bottom=0)
    fig.text(0.55, 0.15, POWER_LABEL if force else REFERENCE_LABEL, ha="center", fontsize=10)
    fig.legend(handles=[Line2D([], [], color="0.15", linewidth=1.2,
                              linestyle=style, label=f"Run {run}")
                        for run, style in enumerate(LINESTYLES, 1)],
               loc="lower center", bbox_to_anchor=(0.55, 0.015), ncol=5,
               frameon=False, handlelength=2.2, columnspacing=1.2)
    save_figure(fig, name, output)


def mean_force(means, groups, output):
    fig, ax = plt.subplots(figsize=(7.1, 4.5))
    fig.subplots_adjust(left=0.13, right=0.98, bottom=0.16, top=0.97)
    for group_index, (group, color, marker) in enumerate(groups[:2]):
        rows = step_rows(means, group)
        ax.errorbar([r["mean_power_W"] for r in rows], [r["mean_force_N"] for r in rows],
                    xerr=[r["between_run_power_SD_W"] for r in rows],
                    yerr=[r["between_run_force_SD_N"] for r in rows],
                    color=color, marker=marker, markersize=3.5,
                    markerfacecolor="white", markeredgewidth=0.85,
                    linewidth=1.1, elinewidth=0.7, capsize=2,
                    linestyle=("-", "--")[group_index],
                    label=DISPLAY_NAMES[group_index])
    power_axes(ax)
    ax.set_ylabel(FORCE_LABEL)
    ax.legend(loc="upper left", frameon=False)
    ax.text(0.97, 0.08, r"Mean $\pm$ 1 SD; $n=5$ runs", transform=ax.transAxes,
            ha="right", va="bottom", fontsize=9)
    save_figure(fig, "configuration_averages", output)


def mean_power(comparison, output):
    fig, axes = plt.subplots(2, 1, figsize=(7.1, 6), sharex=True,
                             gridspec_kw={"height_ratios": [1.6, 1]})
    fig.subplots_adjust(left=0.14, right=0.98, bottom=0.12, top=0.95, hspace=0.25)
    x = [r["reference_fin_target_power_W"] for r in comparison]
    for prefix, label, color, marker, style in (
            ("fin_attached", "Fin attached", "#D55E00", "s", "-"),
            ("fin_removed", "Mechanism without fin", "#009E73", "^", "--")):
        axes[0].errorbar(x, [r[prefix + "_mean_power_W"] for r in comparison],
                         yerr=[r[prefix + "_between_run_power_SD_W"] for r in comparison],
                         color=color, marker=marker, markerfacecolor="white", markersize=3.5,
                         linewidth=1.1, linestyle=style, elinewidth=0.75, capsize=2, label=label)
    reference_axes(axes[0])
    axes[0].set(xlabel="", ylabel=POWER_LABEL, ylim=(0, None))
    axes[0].legend(loc="upper left", frameon=False)
    axes[0].set_title(r"(a) Group means $\pm$ 1 SD ($n=5$ runs per group)",
                      loc="left", fontsize=10)
    axes[1].errorbar(x, [r["attached_minus_removed_power_W"] for r in comparison],
                     yerr=[r["power_difference_SE_W"] for r in comparison],
                     color="#6F438C", marker="o", markerfacecolor="white", markersize=3.5,
                     linewidth=1.1, elinewidth=0.75, capsize=2)
    reference_axes(axes[1])
    axes[1].set_ylabel(r"Power difference, $\Delta\overline{P}$ (W)")
    axes[1].set_title(r"(b) Fin attached minus no fin; bars: $\pm$ 1 SE", loc="left", fontsize=10)
    save_figure(fig, "fin_power_comparison", output)


def force_per_watt(records, means, groups, output):
    fig, ax = plt.subplots(figsize=(7.1, 4.5))
    fig.subplots_adjust(left=0.13, right=0.98, bottom=0.16, top=0.97)
    for group_index, (group, color, marker) in enumerate(groups[:2]):
        # Show the five run-level ratios behind the descriptive mean and SD.
        rows = [r for r in records if r["configuration"] == group]
        ax.scatter([r["mean_power_W"] for r in rows],
                   [r["force_per_watt_N_W"] for r in rows],
                   color=color, marker=marker, s=9, alpha=0.28, linewidths=0)
        average = step_rows(means, group)
        ax.errorbar([r["mean_power_W"] for r in average],
                    [r["mean_run_force_per_watt_N_W"] for r in average],
                    xerr=[r["between_run_power_SD_W"] for r in average],
                    yerr=[r["between_run_force_per_watt_SD_N_W"] for r in average],
                    color=color, marker=marker, markersize=3.5, markerfacecolor="white",
                    linewidth=1.1, linestyle=("-", "--")[group_index],
                    elinewidth=0.7, capsize=2, label=DISPLAY_NAMES[group_index])
    power_axes(ax)
    ax.set_ylabel(r"Mean run-level force per watt (N W$^{-1}$)")
    ax.legend(loc="upper right", frameon=False)
    ax.text(0.97, 0.04, r"Mean $\pm$ 1 SD; $n=5$ runs", transform=ax.transAxes,
            ha="right", va="bottom", fontsize=9)
    save_figure(fig, "force_per_watt", output)


def make_plots(records, means, comparison, groups, output):
    with plt.rc_context({"font.family": "DejaVu Serif", "font.size": 10,
                         "axes.labelsize": 10, "legend.fontsize": 9,
                         "xtick.labelsize": 9, "ytick.labelsize": 9,
                         "mathtext.fontset": "dejavuserif", "axes.linewidth": 0.7,
                         "svg.fonttype": "none", "axes.formatter.useoffset": False}):
        all_runs(records, groups, (0, 1), "mean_power_W", output,
                 "thruster_fin_all_runs", force=True)
        mean_force(means, groups, output)
        all_runs(records, groups, (1, 2), "reference_fin_target_power_W", output,
                 "fin_power_all_runs")
        mean_power(comparison, output)
        force_per_watt(records, means, groups, output)


def write_captions(output):
    (output / "figure_captions.md").write_text("""# Thesis figure captions

Each image is 7.1 inches (180 mm) wide. Place captions below the images in the
thesis; number the figures according to their final order. PNG files are 600 dpi;
SVG files retain vector lines and editable text. Colour, markers and line styles
provide redundant distinctions for print. Do not shrink the two-panel figures
to a single narrow column without checking text legibility.

## thruster_fin_all_runs

Mean signed axial force versus measured mean electrical power for (a) the
thruster and (b) the undulating-fin assembly with the fin attached. Each curve
represents one of five repeated runs and each marker represents one of 20 power
targets. Panels use identical axis scales. Only readings flagged electrically
settled by the controller are included; force and power use the same finite
samples. Signed forces are retained. Lines connect successive settings as visual
guides and are not fitted performance models. Run numbers are local to each
configuration and do not imply paired experiments.

## configuration_averages

Comparison of mean signed axial force and measured electrical power for the
thruster and the complete undulating-fin assembly. Each marker is the equally
weighted mean of five run means at the same nominal power target. Horizontal and
vertical error bars show plus or minus one sample standard deviation of the
five run mean powers and forces, respectively. Error bars describe between-run
variation, not confidence intervals or total measurement uncertainty. Different
configurations can have different measured powers at the same target; no
interpolation or extrapolation is used. Lines are visual guides.

## fin_power_all_runs

Measured mean electrical power for (a) the fin-attached assembly and (b) the
mechanism without the fin, both submerged. Each curve represents one of five
repeated runs and each marker a setting. The horizontal coordinate is the
fin-attached reference target (1 to 20 W); these values do not represent measured
no-fin power. The no-fin tests replay the PWM table derived from the corresponding
fin-attached mean commands. Fin-attached means use electrically settled readings;
no-fin means exclude the first 5 s of each 30 s PWM hold. The panels use identical
axis scales. Lines are visual guides; run numbers do not imply pairing. PWM
matching does not establish equal rotation or undulation frequency.

## fin_power_comparison

(a) Measured electrical power of the submerged fin-attached and no-fin
configurations, averaged equally over five runs at each reference setting.
Error bars show plus or minus one sample standard deviation of the five run
means. (b) Difference between configuration mean powers, defined as fin-attached
minus no-fin power. Difference error bars show plus or minus one standard error,
calculated as sqrt(s_attached^2/5 + s_no_fin^2/5), assuming independent run means
between groups. They are statistical components only, not confidence intervals
or total measurement uncertainty. Reference targets on the horizontal axis label
the corresponding PWM steps, not measured no-fin watts. Sample selection is as
in fin_power_all_runs. The difference is a change in electrical demand associated
with fin attachment and is not a direct measurement of hydrodynamic power or
mechanical loss. Lines are visual guides.

## force_per_watt

Mean run-level signed force per measured electrical watt for the thruster and
the complete undulating-fin assembly. For each run and target, the ratio is
the mean signed force divided by the mean measured power using the same
electrically settled finite samples. Faint markers show individual run ratios.
Prominent markers and vertical error bars show their arithmetic mean and plus
or minus one sample standard deviation across five runs; they are not the mean
of instantaneous sample ratios. Horizontal coordinates and error bars are the
mean and sample standard deviation of the five run mean powers. The mean of
run ratios can differ from the ratio of configuration mean force to mean power.
This dimensional static-force metric is not propulsive efficiency. No no-fin
baseline is subtracted from the complete assembly's electrical power. Negative
values and error-bar portions are retained. Lines are visual guides.

## Limits applying to all figures

Five runs per configuration are the repeated experimental units; within-step
samples are time-correlated and are not counted as independent repeats. The
controller's electrical settled flag does not demonstrate mechanical or force
settling. A fixed 5 s exclusion in PWM tests is a transient allowance, not a
measured settling criterion. Recorded force calibration and sign are retained
without baseline correction. Between-run statistics do not include a complete
budget for calibration, zero drift, alignment, voltage/current measurement,
or other systematic effects. No calibrated force/power uncertainty specification
is supplied to this analysis, so the figures cannot establish absolute accuracy.
Shared calibration effects may also correlate measurements between groups.

Statistical conventions follow the distinction between dispersion of observations,
standard uncertainty of a mean and propagation of uncertainty described in
[NIST TN 1297](https://www.nist.gov/pml/nist-technical-note-1297/nist-tn-1297-appendix-law-propagation-uncertainty).
""", encoding="utf-8")
