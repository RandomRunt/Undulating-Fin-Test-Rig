#include <HX711.h>
#include <Preferences.h>  // ESP32 NVS for persistent storage

// --- Pin Definitions ---
#define DOUT_PIN 18
#define SCK_PIN  19

// --- Calibration Points Config ---
const float KNOWN_WEIGHTS_G[] = { 500.0, 1000.0, 2000.0, 4000.0 };
const int   NUM_WEIGHTS        = sizeof(KNOWN_WEIGHTS_G) / sizeof(KNOWN_WEIGHTS_G[0]);
const float GRAVITY            = 9.80665;
const int   AVG_SAMPLES        = 20;

// --- Globals ---
HX711      scale;
Preferences prefs;

// Calibration results
float rawZero        = 0.0;
float slopeSum       = 0.0;
float calibFactor    = 0.0;  // raw units per gram
float rawReadings[10];        // up to 10 cal points
float knownGrams[10];

// ─────────────────────────────────────────────
//  Helpers
// ─────────────────────────────────────────────

/** Block until the user sends any character over Serial. */
void waitForEnter(const char* prompt = nullptr) {
  if (prompt) { Serial.println(prompt); }
  Serial.println(F("  → Place weight then press ENTER ..."));
  while (Serial.available()) Serial.read();   // flush
  while (!Serial.available()) delay(50);
  while (Serial.available())  Serial.read();  // flush again
}

/** Take AVG_SAMPLES readings and return the mean raw value. */
float averagedRaw(int samples = AVG_SAMPLES) {
  Serial.print(F("  Sampling"));
  double sum = 0.0;
  for (int i = 0; i < samples; i++) {
    while (!scale.is_ready()) delay(10);
    sum += scale.read();
    Serial.print('.');
    delay(50);
  }
  Serial.println();
  return (float)(sum / samples);
}

/** Simple linear regression: y = a + b*x  →  returns slope b */
float linearRegressionSlope(float* x, float* y, int n) {
  float sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0;
  for (int i = 0; i < n; i++) {
    sumX  += x[i];
    sumY  += y[i];
    sumXY += x[i] * y[i];
    sumX2 += x[i] * x[i];
  }
  float denom = (n * sumX2 - sumX * sumX);
  if (fabs(denom) < 1e-9) return 0.0;
  return (n * sumXY - sumX * sumY) / denom;  // raw / gram
}

float linearRegressionIntercept(float* x, float* y, int n, float slope) {
  float sumX = 0, sumY = 0;
  for (int i = 0; i < n; i++) { sumX += x[i]; sumY += y[i]; }
  return (sumY - slope * sumX) / n;
}

// ─────────────────────────────────────────────
//  Tare
// ─────────────────────────────────────────────
void performTare() {
  Serial.println(F("\n========================================"));
  Serial.println(F(" STEP 1 — TARE (Zero Offset)"));
  Serial.println(F("========================================"));
  Serial.println(F("  Remove ALL weight from the load cell."));
  waitForEnter();

  rawZero = averagedRaw();
  Serial.print(F("  Raw zero offset: "));
  Serial.println(rawZero, 2);
}

// ─────────────────────────────────────────────
//  Multi-point Calibration
// ─────────────────────────────────────────────
void performCalibration() {
  Serial.println(F("\n========================================"));
  Serial.println(F(" STEP 2 — MULTI-POINT CALIBRATION"));
  Serial.println(F("========================================"));
  Serial.print(F("  Number of calibration points: "));
  Serial.println(NUM_WEIGHTS);

  // Collect a raw reading for each known weight
  for (int i = 0; i < NUM_WEIGHTS; i++) {
    Serial.println();
    Serial.print(F("  --- Point "));
    Serial.print(i + 1);
    Serial.print(F(" / "));
    Serial.print(NUM_WEIGHTS);
    Serial.print(F("  ["));
    Serial.print(KNOWN_WEIGHTS_G[i], 1);
    Serial.println(F(" g] ---"));

    char buf[64];
    snprintf(buf, sizeof(buf), "  Place %.0f g on the scale.", KNOWN_WEIGHTS_G[i]);
    waitForEnter(buf);

    float raw        = averagedRaw();
    rawReadings[i]   = raw - rawZero;          // net (tared) raw
    knownGrams[i]    = KNOWN_WEIGHTS_G[i];

    Serial.print(F("  Net raw: "));
    Serial.print(rawReadings[i], 2);
    Serial.print(F("  |  Expected: "));
    Serial.print(knownGrams[i], 1);
    Serial.println(F(" g"));
  }

  // Compute calibration factor via linear regression
  // rawReadings = calibFactor * knownGrams  (intercept forced through origin is fine,
  // but we'll use full regression to catch any residual offset).
  float slope     = linearRegressionSlope(knownGrams, rawReadings, NUM_WEIGHTS);
  float intercept = linearRegressionIntercept(knownGrams, rawReadings, NUM_WEIGHTS, slope);
  calibFactor     = slope;   // raw units per gram

  Serial.println(F("\n  === Regression Results ==="));
  Serial.print(F("  Slope  (raw/g)    : ")); Serial.println(slope,     4);
  Serial.print(F("  Intercept (raw)   : ")); Serial.println(intercept, 2);
  Serial.print(F("  calibFactor       : ")); Serial.println(calibFactor, 4);

  // R² goodness-of-fit
  float ssRes = 0, ssTot = 0, meanY = 0;
  for (int i = 0; i < NUM_WEIGHTS; i++) meanY += rawReadings[i];
  meanY /= NUM_WEIGHTS;
  for (int i = 0; i < NUM_WEIGHTS; i++) {
    float predicted = slope * knownGrams[i] + intercept;
    ssRes += (rawReadings[i] - predicted) * (rawReadings[i] - predicted);
    ssTot += (rawReadings[i] - meanY)     * (rawReadings[i] - meanY);
  }
  float r2 = (ssTot > 1e-9) ? (1.0f - ssRes / ssTot) : 1.0f;
  Serial.print(F("  R²                : ")); Serial.println(r2, 6);

  if (r2 < 0.999) {
    Serial.println(F("  ⚠ WARNING: R² < 0.999 — check load cell mounting or wiring."));
  } else {
    Serial.println(F("  ✓ Excellent linearity."));
  }
}

// ─────────────────────────────────────────────
//  Verification Pass
// ─────────────────────────────────────────────
void performVerification() {
  Serial.println(F("\n========================================"));
  Serial.println(F(" STEP 3 — VERIFICATION"));
  Serial.println(F("========================================"));
  Serial.println(F("  Re-test each weight and compare to expected."));
  Serial.println(F("  (calibFactor and rawZero are now applied)\n"));

  float maxErrPct = 0.0;

  for (int i = 0; i < NUM_WEIGHTS; i++) {
    Serial.print(F("  Place "));
    Serial.print(KNOWN_WEIGHTS_G[i], 1);
    Serial.print(F(" g"));
    waitForEnter();

    float raw      = averagedRaw();
    float measured = (raw - rawZero) / calibFactor;
    float errPct   = fabs(measured - KNOWN_WEIGHTS_G[i]) / KNOWN_WEIGHTS_G[i] * 100.0f;
    if (errPct > maxErrPct) maxErrPct = errPct;

    Serial.print(F("  Expected: ")); Serial.print(KNOWN_WEIGHTS_G[i], 1); Serial.print(F(" g"));
    Serial.print(F("  |  Measured: "));  Serial.print(measured, 2); Serial.print(F(" g"));
    Serial.print(F("  |  Error: "));     Serial.print(errPct, 3);  Serial.println(F(" %"));
  }

  Serial.println();
  if (maxErrPct <= 0.5f) {
    Serial.println(F("  ✓ PASS — Max error ≤ 0.5%"));
  } else if (maxErrPct <= 1.0f) {
    Serial.println(F("  ~ ACCEPTABLE — Max error ≤ 1.0%. Consider more averages."));
  } else {
    Serial.println(F("  ✗ FAIL — Max error > 1.0%. Recalibrate or check hardware."));
  }
}

// ─────────────────────────────────────────────
//  Save to NVS
// ─────────────────────────────────────────────
void saveCalibration() {
  prefs.begin("loadcell", false);
  prefs.putFloat("zero",   rawZero);
  prefs.putFloat("factor", calibFactor);
  prefs.end();

  Serial.println(F("\n  ✓ Calibration saved to NVS (persists across resets)."));
  Serial.println(F("  Keys: 'loadcell/zero', 'loadcell/factor'"));
}

// ─────────────────────────────────────────────
//  Print final snippet for use in main firmware
// ─────────────────────────────────────────────
void printFirmwareSnippet() {
  Serial.println(F("\n========================================"));
  Serial.println(F(" COPY THIS INTO YOUR MAIN FIRMWARE"));
  Serial.println(F("========================================"));
  Serial.println(F("  Preferences prefs;"));
  Serial.println(F("  prefs.begin(\"loadcell\", true);"));
  Serial.println(F("  float rawZero    = prefs.getFloat(\"zero\",   0.0);"));
  Serial.println(F("  float calibFactor= prefs.getFloat(\"factor\", 1.0);"));
  Serial.println(F("  prefs.end();"));
  Serial.println(F("  // Then to read weight in grams:"));
  Serial.println(F("  // float grams = (scale.read() - rawZero) / calibFactor;"));
  Serial.println(F("  // float newtons = grams * 9.80665 / 1000.0;"));
  Serial.println(F("========================================\n"));

  Serial.print(F("  Saved rawZero    = ")); Serial.println(rawZero,     2);
  Serial.print(F("  Saved calibFactor= ")); Serial.println(calibFactor, 6);
}

// ─────────────────────────────────────────────
//  Setup & Loop
// ─────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(500);

  Serial.println(F("\n╔══════════════════════════════════════╗"));
  Serial.println(F("║  HX711 5 kg Load Cell Calibration   ║"));
  Serial.println(F("║  ESP32  •  Multi-point  •  NVS save ║"));
  Serial.println(F("╚══════════════════════════════════════╝"));

  scale.begin(DOUT_PIN, SCK_PIN);

  // Wait for HX711 to settle
  Serial.print(F("\nWaiting for HX711"));
  while (!scale.is_ready()) { Serial.print('.'); delay(100); }
  Serial.println(F(" ready.\n"));
  scale.set_gain(128);  // Channel A, gain 128 (default for most HX711 breakouts)
  delay(200);

  // Run calibration sequence
  performTare();
  performCalibration();
  performVerification();
  saveCalibration();
  printFirmwareSnippet();
}

void loop() {
  // Live readout so you can confirm the calibration looks right
  if (scale.is_ready()) {
    float raw    = scale.read();
    float grams  = (raw - rawZero) / calibFactor;
    float newtons = grams * GRAVITY / 1000.0f;

    Serial.print(F("Live — Raw: "));
    Serial.print(raw, 0);
    Serial.print(F("  |  "));
    Serial.print(grams, 2);
    Serial.print(F(" g  |  "));
    Serial.print(newtons, 4);
    Serial.println(F(" N"));
  }
  delay(500);
}

