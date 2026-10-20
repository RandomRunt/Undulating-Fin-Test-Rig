# Test-rig software

Python tools for fin geometry, USB serial recording, and offline load-cell calibration.

## Files

| File | Purpose | Dependencies |
|---|---|---|
| [FinGenerator.py](FinGenerator.py) | Calculate fin flat-pattern dimensions and display a 3D fin surface. | NumPy, Matplotlib, SciPy |
| [SerialLogger.py](SerialLogger.py) | Control Thesis-DAQ through a serial console, with optional CSV recording. | pySerial |
| [PlotRecording.py](PlotRecording.py) | Plot CSV or terminal logs and summarise force per electrical watt at each PWM command or target watt level. | Matplotlib |
| [LoadCellCalibration.py](LoadCellCalibration.py) | Extract firmware calibration from logs, or fit raw CSV readings; optionally plot calibration and residuals. | Standard library; Matplotlib for plots |

## Setup

Use Python 3. Run all commands below from the **repository root**. Install the packages needed for your scripts, or install all dependencies with:

```powershell
python -m pip install numpy matplotlib scipy pyserial
```

Logging requires a device running [Thesis-DAQ firmware](../firmware/Thesis-DAQ/README.md). Build and flash it with ESP-IDF, then close ESP-IDF Monitor before opening the logger on the native USB port.

## Generate fin dimensions

Edit the physical parameters at the top of `FinGenerator.py`: chassis length, pivot offset, propeller outer/hub radii, sweep angles, and wave count. Dimensions are in millimetres; input angles are in degrees.

```powershell
python software/FinGenerator.py
```

The script prints inner/outer edge material lengths and Fusion 360 sketch parameters (radial width, sweep angle, and inner radius), then opens a 3D plot. It does not export a CAD file.

`theta_fin_sweep` sets the total sweep used to size the membrane; `theta_max_deg` sets the motion angle per side. Keep them consistent for your design. The plot title currently says an 8 mm pivot offset; the calculation uses `R_pivot` (currently 17 mm).

## Record sensor data

Find the port, then connect (replace `COM5` with your device's port):

```powershell
python software/SerialLogger.py --list-ports
python software/SerialLogger.py --port COM5 --name zero
python software/SerialLogger.py --port COM5 --no-csv
```

1. On connection, the logger sends **`11`** to request the firmware menu and begins the terminal transcript. Choose the data/test mode you want from the displayed menu.
2. Enter `exit` to stop the stream and return to the firmware menu.
3. Enter `/quit` to close the console, or choose another data/test mode for another recording.

Files are saved under `recordings/` with a label and timestamp. The logger prints each CSV path and its final row count. Use `--name load_1kg` to label another session, `--output-dir PATH` to change the folder, or `--baud 115200` to set the baud rate (115200 is the default). Labels accept letters, digits, underscores, and hyphens.

CSV saving is on by default (`--csv`). Start with `--no-csv` to save only the
terminal transcript. During a session, `/csv off` closes the current CSV file,
`/csv on` opens a new file using the active stream's header, and `/csv` reports
the setting. These commands stay on the host and do not change motor operation
or stop firmware output. Enabling before a CSV header arrives waits for one.
The terminal transcript stays enabled throughout. Formatted output is retained
in the transcript; toggling CSV does not convert formatted lines into CSV rows.
Entering `11` repeats the menu without changing the active mode. During a CSV
stream it also refreshes the header, starting a new CSV file when saving is on.
The startup request therefore lets the logger attach to an already running CSV
mode; it does not automatically select sensor output or start a motor test.

- Each CSV header or backwards device timestamp starts a new file; existing files are never overwritten.
- CSV preserves firmware columns, units, blank values, and sensor statuses. Failed sensor readings remain in the CSV; malformed rows and incomplete final lines are excluded.
- A separate `*_terminal.log` stores received serial bytes and command annotations. Options **2, 5 and 9 produce transcript output only**; use **option 3** for calibration CSV or **option 8** for power-test CSV.
- Firmware commands pass through normally. `/help` shows console help. `/quit` and Ctrl+C attempt to send `exit` before closing; the logger does not reconnect automatically.

If the port is busy, close ESP-IDF Monitor. Enter `11` to request the menu/header
again. If the firmware does not recognize option 11, rebuild and flash the
updated Thesis-DAQ firmware.

## Plot a recording

From the repository root:

```powershell
python software/PlotRecording.py software/recordings/daq_20261007_235818_490431_terminal.log
```

Pass any Thesis-DAQ `.log` or `.csv` path, or omit the path to be prompted for one.
The Matplotlib window shows force, power, current and PWM versus device time,
plus mean power and force per watt at each PWM setting. PWM is a motor command
in microseconds, not measured RPM. Repeated visits to a setting are pooled.

The default `--settle-seconds 1` excludes the first second after each PWM change
or recording block. Force per watt is **mean signed force / mean electrical
power (N/W)** using paired valid readings with power above `--min-power 0.01` W.
It is not a dimensionless efficiency or a mean of instantaneous ratios.

For power-controlled tests (firmware options 8 and 9), the plotter groups rows
by `target_power_W`, excludes rows without `power_settled=1`, and allows PWM to
vary during a target's measurement window. The firmware already requires an
uninterrupted settling interval; `--settle-seconds` additionally excludes time
after a recording block or target change. Summary CSVs include the target watts,
mean commanded PWM, measured mean watts, force and N/W. The lower plots show
force and N/W against **measured** mean watts. In mixed-mode recordings these
lower plots show the power tests; the summary CSV also retains PWM-mode groups.
Targets with no settled readings produce no summary. Settled portions before
a later loss of regulation remain included; inspect target-completion and stop
notices in the transcript to confirm each requested hold finished.

Use the same target range, dwell and measurement point for the fin mechanism and
T200. Start with option `10`, enter `set 5 15 5 5` for 5, 10 and 15 W with five
seconds of settled data per target, then `exit` and `8`. Option `9` gives readable
force in newtons and power in watts and requires on-device force calibration.
See the [power settings and limits](../firmware/Thesis-DAQ/README.md#power-controlled-tests-options-8-9-and-10)
before increasing the range. For example, record two devices separately:

```powershell
python software/SerialLogger.py --port COM5 --name fin --output-dir software/recordings
python software/SerialLogger.py --port COM5 --name t200 --output-dir software/recordings
```

Close one logger session before opening the next. Both modes include target,
filtered power, settled status and step number in their recorded output.

Uncalibrated recordings show raw force counts; N/W requires calibrated force.
Apply the JSON produced by the calibration tool below to raw counts with:

```powershell
python software/PlotRecording.py software/recordings/session.log --calibration recordings/calibration.json --save recordings/session.png --summary-csv recordings/session_summary.csv
```

An external calibration overrides recorded force wherever raw counts are
available. Calibrated formatted logs already contain newtons and can be plotted
directly. Use `--no-show` for saving without opening a window. Summary CSV files
are never overwritten. Plot files at `--save` are overwritten if they exist.
Missing readings appear as gaps; short transients between samples and events
after the logger stops printing cannot be recovered by plotting.

## Calibrate the load cell

For a terminal log recorded during firmware **option 1**, extract the completed calibration directly:

```powershell
python software/LoadCellCalibration.py software/recordings/daq_20261015_155327_524770_terminal.log --output software/recordings/calibration_from_log.json --plot
```

The script preserves the firmware's fitted coefficients rather than refitting its rounded point summaries. It prints known loads, mean counts, and residuals; firmware residuals are used when present, otherwise residuals are calculated from the rounded summaries. The latest completed fit is selected and its number reported. Use `--session 1` to select the first completed fit, for example. An unfinished later calibration does not replace a completed fit.

Omit `--plot` for text and JSON only. Use `--save-plot software/recordings/calibration.png` to save the fit and residual plots without opening a window; combine it with `--plot` to also display them. Existing JSON files are never overwritten; choose a new output name. Plot images at the requested path are overwritten.

Apply the JSON to experimental recordings with `PlotRecording.py --calibration <json-path>`. That script plots test measurements and force/power results; `LoadCellCalibration.py --plot` plots calibration quality. `FinGenerator.py` remains the separate fin-design tool.

Alternatively, calculate a new fit from raw CSV readings:

Record settled readings at zero and several known signed forces using option 3. Supply forces in **newtons**, including any hanger load (`force = mass_kg * 9.80665` for a hanging mass). The CSV does not contain the reference load.

Replace the example CSV paths with your recordings:

```powershell
python software/LoadCellCalibration.py --point 0 recordings/zero.csv --point 9.80665 recordings/loaded.csv --output recordings/calibration.json
```

For several load intervals in one recording, add inclusive start/end times in **seconds since device boot**, derived from `time_us`:

```powershell
python software/LoadCellCalibration.py --point 0 recordings/run.csv 10 15 --point 9.80665 recordings/run.csv 25 30 --point 19.6133 recordings/run.csv 40 45
```

Choose settled intervals that do not span reboots. Each point needs at least two valid samples, and the fit needs at least two different known forces with sufficient raw-count variation. Negative forces are supported.

The script averages `force_raw` readings with `force_status = ESP_OK`, ignores the existing `force_N` field, and weights each point equally. Power-sensor status does not affect calibration. It accepts menu chatter and repeated CSV headers; disable host timestamp prefixes if capturing with IDF Monitor.

Output includes coefficients for:

```text
force_N = (force_raw - tare_counts) * newtons_per_count
```

Review count standard deviations and force residuals, then verify against loads not used in the fit. Optional `--output` saves coefficients, source paths, intervals, and statistics as JSON without overwriting existing files. Dropped-line warnings show the largest cumulative firmware counter observed within the selected interval and may include earlier losses.

Calibration is computed offline and is not uploaded to the device. Use firmware **option 1** for on-device calibration; those settings are RAM-only and are lost on reboot.

## Verification

```powershell
python -m unittest discover -s software/tests -v
```

Tests cover startup menu requests and attaching to active CSV output, CSV switching/resuming, local console commands, clock restarts,
legacy recordings, calibrated parsing and settled power-target summaries.
