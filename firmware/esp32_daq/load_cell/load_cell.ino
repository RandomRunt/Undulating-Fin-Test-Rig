#include "HX711.h"

// Pin definitions
const int LOADCELL_DOUT_PIN = 18;
const int LOADCELL_SCK_PIN = 19;

HX711 scale;

void setup() {
  Serial.begin(115200);
  Serial.println("Initializing the scale...");

  scale.begin(LOADCELL_DOUT_PIN, LOADCELL_SCK_PIN);

  // This value is obtained by calibrating the scale with known weights
  // For now, we use 1 as a placeholder
  scale.set_scale(1.f);                      
  scale.tare();               // Reset the scale to 0

  Serial.println("Readings:");
}

void loop() {
  if (scale.is_ready()) {
    long reading = scale.get_units(10); // Average of 10 readings
    Serial.print("Weight: ");
    Serial.println(reading);
  } else {
    Serial.println("HX711 not found.");
  }

  delay(1000);
}
