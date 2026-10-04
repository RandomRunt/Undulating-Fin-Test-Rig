/*
  ESP32-S3 bench test for the thesis test-rig DAQ sensors:
    - SparkFun HX711 load-cell ADC breakout
    - Adafruit NAU7802 load-cell ADC breakout
    - Adafruit INA260 current/voltage/power monitor

  Arduino Library Manager dependencies:
    - HX711 Arduino Library by Bogdan Necula
    - Adafruit NAU7802 Library
    - Adafruit INA260 Library
    - Adafruit BusIO (dependency of both Adafruit sensor libraries)

  Open Serial Monitor at 115200 baud. Send "t" to tare both load-cell
  channels. Calibration factors below are placeholders until calibrated.
*/

#include <Wire.h>
#include <HX711.h>
#include <Adafruit_NAU7802.h>
#include <Adafruit_INA260.h>

// Change these four pins to match the ESP32-S3 board and test-rig wiring.
constexpr uint8_t I2C_SDA_PIN = 8;
constexpr uint8_t I2C_SCL_PIN = 9;
constexpr uint8_t HX711_DOUT_PIN = 18;
constexpr uint8_t HX711_SCK_PIN = 19;

constexpr uint32_t SERIAL_BAUD = 115200;
constexpr uint32_t PRINT_INTERVAL_MS = 500;
constexpr float HX711_CALIBRATION_FACTOR = 1.0f;
constexpr float NAU7802_CALIBRATION_FACTOR = 1.0f;

HX711 hx711;
Adafruit_NAU7802 nau7802;
Adafruit_INA260 ina260;

bool hx711Found = false;
bool nau7802Found = false;
bool ina260Found = false;
uint32_t lastPrintMs = 0;
int32_t nau7802ZeroOffset = 0;

// Average NAU7802 samples without waiting forever if the device stops responding.
bool readNau7802Average(uint8_t sampleCount, int32_t &average) {
  int64_t sum = 0;
  uint8_t samplesRead = 0;
  const uint32_t startMs = millis();

  while (samplesRead < sampleCount && millis() - startMs < 3000) {
    if (nau7802.available()) {
      sum += nau7802.read();
      samplesRead++;
    } else {
      delay(1);
    }
  }

  if (samplesRead != sampleCount) {
    return false;
  }
  average = static_cast<int32_t>(sum / sampleCount);
  return true;
}

// Tare load cells for both HX711 and NAU7802 if they are detected. This should be done with no load applied to the load cells.
void tareLoadCells() {
  Serial.println("Taring load-cell ADCs; remove all applied load...");

  if (hx711Found && hx711.wait_ready_timeout(1000)) {
    hx711.tare(20);
    Serial.println("HX711 tare complete.");
  } else {
    Serial.println("HX711 tare skipped (not detected or not ready).");
  }

  if (nau7802Found) {
    int32_t newOffset = 0;
    if (readNau7802Average(64, newOffset)) {
      nau7802ZeroOffset = newOffset;
      Serial.println("NAU7802 tare complete.");
    } else {
      Serial.println("NAU7802 tare failed (samples timed out).");
    }
  } else {
    Serial.println("NAU7802 tare skipped (not detected).");
  }
}

// Serial print data and status of all three sensors. This is called once at setup and then periodically in loop().
void printSensorStatus() {
  Serial.println();
  Serial.println("ESP32-S3 sensor test results");
  Serial.printf("HX711   (DOUT GPIO %u, SCK GPIO %u): %s\n",
                HX711_DOUT_PIN, HX711_SCK_PIN,
                hx711Found ? "FOUND" : "NOT FOUND");
  Serial.printf("NAU7802 (I2C 0x2A): %s\n",
                nau7802Found ? "FOUND" : "NOT FOUND");
  Serial.printf("INA260  (I2C 0x40): %s\n",
                ina260Found ? "FOUND" : "NOT FOUND");
  Serial.println("Send 't' to tare the available load-cell ADCs.");
  Serial.println();
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(1500); // Allow USB CDC Serial Monitor time to attach.

  Serial.println("Starting undulating-fin test-rig sensor check...");
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  Wire.setClock(400000);

  hx711.begin(HX711_DOUT_PIN, HX711_SCK_PIN);
  hx711Found = hx711.wait_ready_timeout(1500);
  if (hx711Found) {
    hx711.set_scale(HX711_CALIBRATION_FACTOR);
  }

  nau7802Found = nau7802.begin(&Wire);
  if (nau7802Found) {
    // Settings for a single load cell on the Adafruit breakout.
    nau7802.setLDO(NAU7802_3V3);
    nau7802.setGain(NAU7802_GAIN_128);
    nau7802.setRate(NAU7802_RATE_80SPS);
    nau7802.setPGACap(true);

    // Discard startup conversions, then calibrate the ADC internal offset.
    int32_t discarded = 0;
    readNau7802Average(10, discarded);
    if (!nau7802.calibrate(NAU7802_CALMOD_INTERNAL)) {
      Serial.println("Warning: NAU7802 internal calibration failed.");
    }
  }

  ina260Found = ina260.begin(INA260_I2CADDR_DEFAULT, &Wire);

  printSensorStatus();
  if (hx711Found || nau7802Found) {
    tareLoadCells();
  }
}

void loop() {
  while (Serial.available() > 0) {
    const char command = Serial.read();
    if (command == 't' || command == 'T') {
      tareLoadCells();
    }
  }

  const uint32_t now = millis();
  if (now - lastPrintMs < PRINT_INTERVAL_MS) {
    return;
  }
  lastPrintMs = now;

  Serial.printf("time_ms=%lu", static_cast<unsigned long>(now));

  if (hx711Found && hx711.wait_ready_timeout(100)) {
    Serial.printf(", HX711_raw=%ld, HX711_units=%.3f",
                  static_cast<long>(hx711.read()), hx711.get_units(5));
  } else {
    Serial.print(", HX711=NOT_READY");
  }

  if (nau7802Found && nau7802.available()) {
    const int32_t raw = nau7802.read();
    const float units = static_cast<float>(raw - nau7802ZeroOffset) /
                        NAU7802_CALIBRATION_FACTOR;
    Serial.printf(", NAU7802_raw=%ld, NAU7802_units=%.3f",
                  static_cast<long>(raw), units);
  } else {
    Serial.print(", NAU7802=NOT_READY");
  }

  if (ina260Found) {
    Serial.printf(", INA260_V=%.4f, INA260_A=%.4f, INA260_W=%.4f",
                  ina260.readBusVoltage() / 1000.0f,
                  ina260.readCurrent() / 1000.0f,
                  ina260.readPower() / 1000.0f);
  } else {
    Serial.print(", INA260=NOT_FOUND");
  }

  Serial.println();
}
