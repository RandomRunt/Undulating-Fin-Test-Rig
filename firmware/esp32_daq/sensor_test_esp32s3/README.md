# ESP32-S3 DAQ sensor test

Open `sensor_test_esp32s3.ino` directly in Arduino IDE. The folder and sketch
names match, as required by Arduino IDE.

## Arduino IDE setup

1. Install the **esp32 by Espressif Systems** board package.
2. Select the exact ESP32-S3 board and its serial port under **Tools**.
3. Install these libraries with Library Manager:
   - **HX711 Arduino Library** by Bogdan Necula
   - **Adafruit NAU7802**
   - **Adafruit INA260**
   - Accept the **Adafruit BusIO** dependency when prompted
4. Upload the sketch and open Serial Monitor at **115200 baud**.

If native USB is being used, enable **USB CDC On Boot** in the board's Tools
menu when that option is available.

## Default wiring

All modules must share GND. Power the sensor breakout logic from **3.3 V**
unless its manufacturer explicitly documents ESP32-safe level shifting.

| Sensor | Sensor pin | ESP32-S3 pin |
|---|---|---|
| SparkFun HX711 | DT/DOUT | GPIO 18 |
| SparkFun HX711 | SCK/CLK | GPIO 19 |
| Adafruit NAU7802 | SDA | GPIO 8 |
| Adafruit NAU7802 | SCL | GPIO 9 |
| Adafruit INA260 | SDA | GPIO 8 |
| Adafruit INA260 | SCL | GPIO 9 |

The NAU7802 and INA260 share I2C safely at their default addresses, `0x2A`
and `0x40`. Change the four pin constants near the top of the sketch if these
GPIO assignments conflict with the particular ESP32-S3 board.

Wire each load cell to its ADC breakout according to the breakout/load-cell
manufacturer's excitation and signal labels. The SparkFun HX711 uses its
two-wire clock/data interface; the two Adafruit boards share the I2C bus via
their STEMMA QT connectors or SDA/SCL pins. INA260 high-current terminals
must be wired in series with the measured supply; do not route load current
through the ESP32 or breadboard power rails.

## Expected output

At startup, the sketch reports `FOUND` or `NOT FOUND` for each device, tares
detected load-cell ADCs, and prints comma-separated raw/load values plus INA260
voltage, current, and power every 500 ms. Send `t` in Serial Monitor to tare
both load-cell channels again.

The two calibration factors intentionally default to `1.0`. Raw readings are
therefore useful for checking wiring and response, but the displayed load
units are not physical units until each load-cell channel is calibrated.
