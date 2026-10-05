# Thesis DAQ menu firmware

ESP-IDF target: `esp32c3`. Build and flash with the UART flash method, then open
IDF Monitor on the native USB COM port. The ESC starts at 1500 us neutral.
Sensors are read quietly in the background; no measurement stream starts until
selected. Type an option number and press Enter.

| Option | Function |
|---|---|
| 1 | Guided multi-point force calibration |
| 2 | Formatted timestamped sensor output |
| 3 | Unformatted timestamped sensor output (CSV) |
| 4 | PWM sweep with step notices only |
| 5 | PWM sweep with formatted timestamped sensor output |
| 6 | View/change current GPIO assignments |
| 7 | View/change PWM test settings |

**Type `exit` and press Enter in any mode:** stop printing/recording/testing,
return PWM to 1500 us neutral, and show the original menu. `stop` also does this.
Unlike earlier firmware, a lone `x` is not a stop command; it is part of `exit`.
Finish a mode with `exit` before selecting another option.

## Wiring and pin settings

| Connection | Default ESP32-C3 Super Mini GPIO |
|---|---|
| Both sensor SDA pins | GPIO0 |
| Both sensor SCL pins | GPIO1 |
| Basic ESC white signal wire | GPIO3 |
| Both breakout VIN pins | 3V3 |
| Both breakout grounds and ESC signal ground | GND |

### S-type load cell to NAU7802

Connect the load cell to channel 1 (A), which this firmware reads. For the common
red/black/white/green/yellow cable, the usual mapping is:

| Load cell wire | NAU7802 terminal | Function |
|---|---|---|
| Red | E+ | Bridge excitation positive |
| Black | E- | Bridge excitation negative |
| Green | A+ | Channel 1 signal positive |
| White | A- | Channel 1 signal negative |
| Yellow | Shield/GND, if confirmed as shield | Cable shield; not an ADC signal |
| None | B+ | Leave unconnected; channel 2 signal positive |
| None | B- | Leave unconnected; channel 2 signal negative |

Wire colours are not universal: confirm this mapping against the specific load
cell's datasheet or label before powering it (For this JLBS-MD-5kg, a full bridge gives roughly 250 Ohms across opposite pairs and ~250 Ohms across other combinations). Yellow is commonly a shield/drain
wire, but its role cannot be confirmed from colour alone. If confirmed as shield,
connect it to the breakout's dedicated shield terminal, if present, or circuit
GND at the ADC end only. E- may be used only if the breakout documents it as GND.
If its role is unknown, leave yellow insulated until verified; do not connect it
to B+ or B-.

E+/E- power the load cell bridge; A+/A- measure its small differential output.
B+/B- are a second differential input pair, not extra excitation or shield
connections. After wiring, check that raw readings respond to an applied load,
then use option 1 to tare and calibrate into newtons. Tension and compression
produce opposite signs; the fitted calibration follows the signed known forces
entered during calibration.

Wiring reference: [SparkFun NAU7802 hardware overview](https://learn.sparkfun.com/tutorials/qwiic-scale-hookup-guide/hardware-overview).

The ESC requires its own motor power supply; its signal connector does not power
the ESP32. GPIO8/9 share LED/BOOT and boot strapping, and GPIO18/19 are native USB.

In option 6, enter `pins 0 1 3` to set SDA, SCL and ESC respectively. Firmware
accepts three different GPIOs from 0, 1, 3, 4, 5, 6, 7, 10, 20, 21. Remove motor
power before rewiring. Changing pins releases the old bus/device handles,
reinitializes sensors and neutral PWM, and clears force calibration. An unchanged
pin assignment can also reinitialize sensors after correcting their wiring.
Settings apply for this session and revert to the defaults in `main.c` on reboot.

Measure the DC supply to the ESC, not the motor phase wires:
power positive -> INA260 IN+ -> INA260 IN- -> ESC positive.
Follow Adafruit's board/current limits; the INA260's 15 A continuous chip rating
is below the Basic ESC's 30 A rating. Check your propulsion device's current
before routing motor power through the breakout.

## Force calibration (option 1)

Keep propulsion stopped. For a horizontal rig, apply known forces along the
normal thrust axis and through the normal mechanical load path. A fixed pulley
can redirect a hanging mass into a horizontal pull, approximately F = m*g;
include hanger mass and account for pulley friction and the rig geometry.

1. Remove applied force. Enter `tare`, then wait for its point summary.
2. Apply a known force and allow the rig to settle.
3. Enter `point 9.80665` if the applied force is +9.80665 N, for example.
4. Wait for its summary, then repeat `point <newtons>` for other loads.
5. Enter `fit` to fit a straight line across the recorded points.
6. Use `show` to inspect calibration, then `exit` to return to the menu.
7. Use output option 2 to verify zero and additional loads not used in the fit.

Each point averages 40 fresh logged readings (about two seconds). Up to eight
points including zero can be recorded. `fit` needs at least two different points;
several loads and repeated loading/unloading provide a better check. Firmware
prints each point's mean counts, the fitted coefficients and residual errors.

`force_N = (raw_counts - tare_counts) * newtons_per_count`.
The sign follows the known forces you enter. A new `tare` changes zero while
retaining an existing scale factor, and starts a fresh point dataset. `exit`
cancels an unfinished recording but retains completed points and calibration.
Calibration is RAM-only and is lost on reboot. Save the printed coefficients and
point summaries with your experimental records. Startup ADC internal calibration
is separate from calibration into newtons.

## Sensor output (options 2 and 3)

Formatted output uses the requested labels:

```text
Timestamp: 123456 us, Force: 2.500000 N, Power: 12.0000 W, Current PWM: 1500 us
```

Before calibration, Force explicitly shows raw counts and `(uncalibrated)`.
A failed force read displays `unavailable`; failed power reads display `nan`.

CSV output prints a header once, then numeric/status rows:

```text
time_us,force_raw,force_N,voltage_V,current_A,power_W,pulse_us,power_status,force_status,dropped_lines
```

The force_N field is blank until calibrated. Failed force reads have empty fields.
Check for `ESP_OK` in both status columns; `ESP_ERR_NOT_FINISHED` means no fresh
conversion. `dropped_lines` counts output lost to a full USB buffer, including
output before the monitor connects. Commands are echoed in menus/settings, but
not while streaming, keeping typed text out of CSV rows.

## PWM settings and tests (options 7, 4 and 5)

Defaults: neutral/start 1500 us, maximum 1700 us, 50 us increments, five seconds
at each step, 50 Hz pulse frequency. In option 7, `set 1700 50 5` sets the maximum,
increment and hold seconds. Maximum is 1500..1900; increment must be positive and
divide the range exactly; dwell is an integer 1..60 seconds. Settings are RAM-only.

Choose option 4 or 5 to start the configured test explicitly. With defaults:
1500 -> 1550 -> 1600 -> 1650 -> 1700 -> 1500 us. The initial neutral step and each
subsequent step last five seconds. Completion returns to neutral and the menu.
Option 4 prints only step/test notices; option 5 adds formatted measurement rows.
These are throttle pulse widths, not measured RPM. Confirm the powered ESC's
initialization tones before starting a test; firmware enforces five seconds of
neutral after configuring its output.

Tests also stop on sensor errors, data older than 0.5 seconds, and detected USB
disconnection. Closing a terminal may leave USB connected: enter `exit` before
closing it. Software is not a substitute for an accessible motor-power cutoff.

## Timing and recording

Data modes print approximately 20 rows/s. INA260 uses triggered voltage/current
conversions, 1.1 ms each, without averaging; after reading, firmware triggers the
next conversion. Power represents the preceding interval, roughly one log period
old. NAU7802 runs at 80 samples/s, gain 128, 3.0 V excitation, channel 1; logging
captures a subset. Timestamp is the read-loop time in microseconds since boot.
Sensors are not sampled simultaneously. PWM widths round to about 1.22 us steps.

For steady thrust-per-watt results, exclude settling after each command change
and divide mean force by mean power over matching settled windows. Check raw
force, sensor status, missing rows and calibration before accepting a run.

In IDF Monitor, press Ctrl+T then Ctrl+L to start/stop saving a log in the project
directory. Keep host timestamps disabled for CSV, and exclude menu/diagnostic
lines when importing data.

## Code and verification

- `main/main.c`: pins, menu, PWM, calibration and experiment loop.
- `main/sensors.c`: native ESP-IDF sensor initialization and register reads.
- `tests/menu_test.c`: actual menu logic exercised with simulated hardware APIs.

On a host with GCC, run:

```text
gcc -std=c11 -Wall -Wextra -Werror -Itests/include tests/menu_test.c -o build/menu_test.exe
build/menu_test.exe
```

The host tests cover silent modes, output formats, `exit`, invalid settings,
calibration fitting/re-tare, PWM stepping, completion and stale-data shutdown.
They do not replace checking PWM timing and measurements on the physical rig.

References: [ESP-IDF I2C](https://docs.espressif.com/projects/esp-idf/en/stable/esp32c3/api-reference/peripherals/i2c.html),
[LEDC](https://docs.espressif.com/projects/esp-idf/en/stable/esp32c3/api-reference/peripherals/ledc.html),
[IDF Monitor](https://docs.espressif.com/projects/esp-idf/en/stable/esp32c3/api-guides/tools/idf-monitor.html),
[Basic ESC](https://bluerobotics.com/store/thrusters/speed-controllers/besc30-r3/),
[INA260 datasheet](https://www.ti.com/lit/ds/symlink/ina260.pdf),
[NAU7802 datasheet](https://www.nuvoton.com.cn/export/resource-files/en-us--DS_NAU7802_DataSheet_EN_Rev2.6.pdf).
