# Test-rig software

Python tools for fin geometry, USB serial recording, and offline load-cell calibration.

## Files

| File | Purpose | Dependencies |
|---|---|---|
| [FinGenerator.py](FinGenerator.py) | Calculate fin flat-pattern dimensions and display a 3D fin surface. | NumPy, Matplotlib, SciPy |
| [SerialLogger.py](SerialLogger.py) | Control Thesis-DAQ through a serial console and save option 3 streams as CSV. | pySerial |
| [PlotRecording.py](PlotRecording.py) | Plot CSV or terminal logs and summarise force per electrical watt at each PWM command. | Matplotlib |
| [LoadCellCalibration.py](LoadCellCalibration.py) | Fit force calibration coefficients from recorded raw load-cell counts. | Python standard library |

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
```

1. Enter `3` to start CSV recording.
2. Enter `exit` to stop the stream and return to the firmware menu.
3. Enter `/quit` to close the console, or `3` to start another recording.

Files are saved under `recordings/` with a label and timestamp. The logger prints each CSV path and its final row count. Use `--name load_1kg` to label another session, `--output-dir PATH` to change the folder, or `--baud 115200` to set the baud rate (115200 is the default). Labels accept letters, digits, underscores, and hyphens.

- Each CSV header or backwards device timestamp starts a new file; existing files are never overwritten.
- CSV preserves firmware columns, units, blank values, and sensor statuses. Failed sensor readings remain in the CSV; malformed rows and incomplete final lines are excluded.
- A separate `*_terminal.log` stores received serial bytes and host command annotations. Options **2 and 5 produce transcript output only**; use **option 3** for calibration CSV.
- Firmware commands pass through normally. `/help` shows console help. `/quit` and Ctrl+C attempt to send `exit` before closing; the logger does not reconnect automatically.

If the port is busy, close ESP-IDF Monitor. If no menu appears or you connected during a stream, enter `exit`, then `3` to capture a fresh CSV header.

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
