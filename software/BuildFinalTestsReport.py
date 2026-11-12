"""Build and render the final-test PDF report from verified plots and CSVs.

Requires reportlab, pypdf and pypdfium2. Outputs are confined to output/pdf
and tmp/pdfs/final_test_report; measurement logs and figure inputs are read only.
"""

import csv
from html import escape
import json
from pathlib import Path
import re

import matplotlib
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak,
)


ROOT = Path(__file__).resolve().parents[1]
PLOTS = ROOT / "recordings" / "Tests Final" / "plots"
OUTPUT = ROOT / "output" / "pdf"
QA = ROOT / "tmp" / "pdfs" / "final_test_report"
STEM = "Final_Test_Results_Report"
FIGURES = (
    ("thruster_fin_all_runs", "Individual force and power responses"),
    ("configuration_averages", "Average force and power comparison"),
    ("fin_power_all_runs", "Individual fin attached and no fin power responses"),
    ("fin_power_comparison", "Average power demand and attachment difference"),
    ("force_per_watt", "Static force per electrical watt"),
)


def load_csv(name):
    with (PLOTS / name).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    QA.mkdir(parents=True, exist_ok=True)
    font_dir = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    for name, filename in (("Report", "DejaVuSerif.ttf"),
                           ("Report-Bold", "DejaVuSerif-Bold.ttf"),
                           ("Report-Italic", "DejaVuSerif-Italic.ttf")):
        pdfmetrics.registerFont(TTFont(name, str(font_dir / filename)))
    pdfmetrics.registerFontFamily("Report", normal="Report", bold="Report-Bold",
                                   italic="Report-Italic", boldItalic="Report-Bold")
    styles = {
        "title": ParagraphStyle("ReportTitle", fontName="Report-Bold", fontSize=22,
                                 leading=28, spaceAfter=15, textColor=colors.black),
        "heading": ParagraphStyle("ReportHeading", fontName="Report-Bold", fontSize=13,
                                   leading=18, spaceBefore=12, spaceAfter=7,
                                   textColor=colors.black, keepWithNext=True),
        "body": ParagraphStyle("ReportBody", fontName="Report", fontSize=10.2,
                                leading=14.5, spaceAfter=9),
        "caption": ParagraphStyle("ReportCaption", fontName="Report", fontSize=9,
                                   leading=12.5, spaceBefore=7, spaceAfter=11),
        "small": ParagraphStyle("ReportSmall", fontName="Report", fontSize=8.5,
                                 leading=11.5, spaceAfter=6),
        "cell": ParagraphStyle("ReportCell", fontName="Report", fontSize=8.2,
                                leading=11, alignment=TA_CENTER),
    }
    means = load_csv("configuration_step_averages.csv")
    comparison = load_csv("fin_power_comparison.csv")
    sources = json.loads((PLOTS / "sources.json").read_text(encoding="utf-8"))
    assert len(means) == 60 and len(comparison) == 20 and len(sources) == 15
    def mean(group, step):
        return next(r for r in means if r["configuration"] == group and int(r["step"]) == step)
    last_fin = mean("Undulating fin", 20)
    last_thruster = mean("Thruster", 20)
    last = comparison[-1]
    reductions = [float(r["power_reduction_percent"]) for r in comparison]
    lowest_share, highest_share = 100 - max(reductions), 100 - min(reductions)
    caption_text = (PLOTS / "figure_captions.md").read_text(encoding="utf-8")
    captions = {}
    for name, _ in FIGURES:
        section = re.search(r"^## " + re.escape(name) + r"\n\n(.*?)(?=\n## |\Z)",
                            caption_text, re.M | re.S)
        assert section, name
        captions[name] = " ".join(section.group(1).split()).replace(
            "Sample selection is as in fin_power_all_runs.",
            "Sample selection follows Figure 3.").replace(
            "calculated as sqrt(s_attached^2/5 + s_no_fin^2/5),",
            "calculated from the two group variances and five runs per group,")

    intro = (
        "The final tests compare static axial force and measured electrical power for a "
        "thruster, an undulating-fin assembly, and the submerged mechanism with its fin removed. "
        "The thruster produced greater mean force over the tested range. Removing the fin "
        "reduced electrical demand, while substantial demand remained in the operating mechanism."
    )
    question = (
        "How does the undulating-fin prototype compare with the thruster in static force per "
        "electrical watt, and how does fin attachment change electrical demand at corresponding "
        "PWM commands?"
    )
    endpoint = (
        f"At the highest reference step, the thruster produced {float(last_thruster['mean_force_N']):.2f} "
        f"± {float(last_thruster['between_run_force_SD_N']):.2f} N at "
        f"{float(last_thruster['mean_power_W']):.2f} W. The fin-attached assembly produced "
        f"{float(last_fin['mean_force_N']):.2f} ± {float(last_fin['between_run_force_SD_N']):.2f} N "
        f"at {float(last_fin['mean_power_W']):.2f} W. Force values are means ± one between-run SD "
        "for five runs. These are nearby measured powers, not an exact equal-power comparison."
    )
    baseline = (
        f"Across the 20 corresponding settings, the no-fin mechanism consumed "
        f"{lowest_share:.1f}-{highest_share:.1f}% of the fin-attached mean electrical power. "
        "This is a command-matched baseline comparison. It does not isolate friction losses, "
        "motor efficiency or the mechanical power transferred to the water."
    )
    observations = {
        "thruster_fin_all_runs": (
            "The common scales allow direct visual comparison of the measured force ranges. "
            "The fin-attached runs show greater between-run separation than the thruster runs "
            "over much of the range. This variation should be discussed alongside the mean response; "
            "the curves alone do not identify whether its origin is mechanical, hydrodynamic or instrumental."
        ),
        "configuration_averages": endpoint + " The comparison describes this prototype and test setup; "
            "it does not establish that every undulating-fin design has the same relative performance.",
        "fin_power_all_runs": (
            "The two configurations follow different measured power curves despite closely "
            "corresponding commands. The x-axis reference targets label the fin-attached "
            "operating steps. In particular, the 20 W label does not mean that the no-fin "
            "mechanism drew 20 W. Motor speed or mechanism frequency was not established by PWM matching."
        ),
        "fin_power_comparison": (
            f"At the 20 W reference step, fin-attached and no-fin mean powers were "
            f"{float(last['fin_attached_mean_power_W']):.2f} W and "
            f"{float(last['fin_removed_mean_power_W']):.2f} W. The electrical difference was "
            f"{float(last['attached_minus_removed_power_W']):.2f} W, with a statistical standard "
            f"error of {float(last['power_difference_SE_W']):.2f} W under the independent-group "
            "assumption. Session effects and calibration uncertainty are not included in that standard error."
        ),
        "force_per_watt": (
            "This figure compares the measured static-force output per electrical watt of the "
            "two complete propulsion configurations. The mechanism baseline remains in the "
            "fin assembly's denominator. Ratios at low force require particular care because "
            "run-to-run force variation can be large relative to the mean. The N/W metric "
            "is dimensional and should not be described as swimming propulsive efficiency."
        ),
    }
    methods = [
        ("Sample selection", "Tests 1-5 are thruster runs, 6-10 are fin-attached runs and "
         "11-15 are no-fin runs, sorted by source filename timestamp. Power-controlled tests "
         "retain finite force/power pairs with Settled=1. That flag establishes an electrical "
         "regulation condition, not mechanical settling. No-fin runs exclude the first 5 s "
         "of each 30 s PWM hold as a fixed transient allowance. Signed force and the recorded "
         "calibration are retained without offset correction."),
        ("Repeated experimental units", "A run is the repeated experimental unit, with five "
         "runs per configuration. Each setting is first reduced to a run mean; the five run "
         "means then receive equal weight. Within-step time samples are not counted as "
         "independent repeats. The same run visits all 20 steps, so those steps are not "
         "independent experimental replicates."),
        ("Dispersion and difference", "SD bars use the sample standard deviation of five "
         "run means. They describe repeatability rather than confidence intervals or total "
         "measurement uncertainty. The fin-attached minus no-fin power difference uses two "
         "unpaired group means. Its statistical standard error is calculated from the "
         "two group variances as shown below, assuming independence between groups. No coverage probability "
         "is assigned to the plotted one-SE bars. Statistical conventions follow NIST TN 1297 [1]."),
        ("Command alignment and interpretation", "No-fin runs replay the PWM table derived "
         "from the fin-attached mean commands. The maximum difference from the fin group's "
         "mean command is 0.544 µs. This does not establish equal motor speed, frequency "
         "or fin motion. Configuration and session effects cannot be separated because "
         "the configurations were recorded in separate sessions. A complete measurement "
         "uncertainty budget, including calibration, zero drift and alignment, remains "
         "necessary for claims about absolute accuracy."),
        ("Additional experiment", "Five no-fin runs with the mechanism fully clear of the "
         "water could quantify the change in electrical demand associated with immersion "
         "of the bare mechanism. Replay the same PWM table and measure actual frequency, "
         "voltage, current and power. Include a submerged no-fin check in the new session "
         "to assess changes since the existing tests. This proposed comparison would "
         "remain an electrical baseline study rather than a direct hydrodynamic-power measurement."),
    ]

    pdf_path = OUTPUT / (STEM + ".pdf")
    md_path = OUTPUT / (STEM + ".md")
    doc = SimpleDocTemplate(str(pdf_path), pagesize=A4, rightMargin=18*mm,
                            leftMargin=18*mm, topMargin=18*mm, bottomMargin=18*mm,
                            title="Final Test Results for the Undulating Fin Test Rig",
                            author="", subject="Static force and electrical power comparison")
    story = []
    def para(text, style="body"):
        story.append(Paragraph(escape(text), styles[style]))
    def heading(text):
        para(text, "heading")
    para("Final Test Results for the Undulating Fin Test Rig", "title")
    para("Static force and electrical power comparison  |  12 November 2026", "small")
    para(intro)
    heading("Research question")
    para(question)
    heading("Representative measured results")
    headers = ["Reference<br/>target (W)", "Thruster<br/>power (W)", "Thruster force<br/>(N, mean ± SD)",
               "Fin power<br/>(W)", "Fin force<br/>(N, mean ± SD)"]
    data = [[Paragraph(h, styles["cell"]) for h in headers]]
    md_table = ["| Reference target (W) | Thruster power (W) | Thruster force (N, mean ± SD) | Fin power (W) | Fin force (N, mean ± SD) |",
                "| --- | --- | --- | --- | --- |"]
    for step in (5, 10, 20):
        thruster, fin = mean("Thruster", step), mean("Undulating fin", step)
        values = [str(step), f"{float(thruster['mean_power_W']):.2f}",
                  f"{float(thruster['mean_force_N']):.2f} ± {float(thruster['between_run_force_SD_N']):.2f}",
                  f"{float(fin['mean_power_W']):.2f}",
                  f"{float(fin['mean_force_N']):.2f} ± {float(fin['between_run_force_SD_N']):.2f}"]
        data.append([Paragraph(escape(v), styles["cell"]) for v in values])
        md_table.append("| " + " | ".join(values) + " |")
    table = Table(data, colWidths=[28*mm, 29*mm, 45*mm, 27*mm, 45*mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#E8ECEF")),
        ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#D9D9D9")),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 7),
        ("BOTTOMPADDING", (0,0), (-1,-1), 7),
    ]))
    story.extend([table, Spacer(1, 10)])
    para("Measured powers can differ at the same reference target. Force statistics use five run means.", "small")
    para(endpoint)
    heading("Mechanism baseline")
    para(baseline)

    md = ["# Final Test Results for the Undulating Fin Test Rig", "",
          "Static force and electrical power comparison | 12 November 2026", "", intro,
          "", "## Research question", "", question, "", "## Representative measured results", "",
          *md_table, "", endpoint, "", "## Mechanism baseline", "", baseline]
    for number, (name, title) in enumerate(FIGURES, 1):
        story.append(PageBreak())
        heading(f"Figure {number} {title}")
        image_path = PLOTS / (name + ".png")
        with PILImage.open(image_path) as image:
            width, height = image.size
        figure = Image(str(image_path), width=174*mm, height=174*mm * height/width)
        story.append(figure)
        para(f"Figure {number}. " + captions[name], "caption")
        heading("Interpretation")
        para(observations[name])
        md.extend(["", f"## Figure {number} {title}", "",
                   f"![{title}](../../recordings/Tests%20Final/plots/{name}.png)", "",
                   f"Figure {number}. {captions[name]}", "", observations[name]])
    story.append(PageBreak())
    heading("Analysis method and further experimentation")
    md.extend(["", "## Analysis method and further experimentation"])
    for title, text in methods:
        heading(title)
        para(text)
        md.extend(["", "### " + title, "", text])
        if title == "Dispersion and difference":
            equation = "SE(ΔP) = √(s<sub>attached</sub><super>2</super>/5 + s<sub>no fin</sub><super>2</super>/5)"
            story.append(Paragraph(equation, ParagraphStyle(
                "Equation", parent=styles["body"], alignment=TA_CENTER, spaceAfter=10)))
            md.extend(["", r"$$\mathrm{SE}(\Delta\overline{P}) = \sqrt{\frac{s_{\mathrm{attached}}^2}{5} + \frac{s_{\mathrm{no\ fin}}^2}{5}}$$"])
    reference = ("[1] National Institute of Standards and Technology. NIST Technical Note 1297. "
                 "Appendix A Law of Propagation of Uncertainty. "
                 "https://www.nist.gov/pml/nist-technical-note-1297/"
                 "nist-tn-1297-appendix-law-propagation-uncertainty")
    para(reference, "small")
    md.extend(["", reference, "", "## Source traceability", "",
               "Figures and calculations: software/PlotFinalTests.py and software/final_test_figures.py. "
               "Numeric summaries and source hashes: recordings/Tests Final/plots. "
               "The source manifest identifies all 15 input logs and their SHA-256 hashes."])

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Report", 8)
        canvas.setFillColor(colors.HexColor("#4A4A4A"))
        canvas.drawString(18*mm, 10*mm, "Undulating Fin Test Rig   Final Test Results")
        canvas.drawRightString(A4[0]-18*mm, 10*mm, str(document.page))
        canvas.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")

    from pypdf import PdfReader
    import pypdfium2 as pdfium
    reader = PdfReader(str(pdf_path))
    assert len(reader.pages) == 7, f"Unexpected pagination: {len(reader.pages)} pages"
    for number in range(1, 6):
        assert f"Figure {number}" in reader.pages[number].extract_text()
    for page in reader.pages:
        assert len(page.extract_text().strip()) > 100
    rendered = pdfium.PdfDocument(str(pdf_path))
    for number, page in enumerate(rendered, 1):
        bitmap = page.render(scale=1.6)
        bitmap.to_pil().save(QA / f"page-{number}.png")
        bitmap.close()
        page.close()
    rendered.close()
    print(f"Created {len(reader.pages)}-page PDF: {pdf_path}")
    print(f"Editable Markdown: {md_path}")
    print(f"Rendered all pages for visual review: {QA}")


if __name__ == "__main__":
    main()
