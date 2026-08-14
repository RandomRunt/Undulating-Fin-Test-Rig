#include <HX711.h>

// --- Pin Definitions ---
const int HX711_DT = 4;
const int HX711_SCK = 5;

// --- Objects ---
HX711 scale;

// --- Calibration Factor ---
// You MUST calculate this for your specific load cell.
// Formula: Calibration Factor = (Raw Reading) / (Known Weight)
float calibration_factor = 2280.0; 

void setup() {
  Serial.begin(115200);
  while (!Serial) { delay(10); } // Wait for serial port to connect
  
  Serial.println("HX711 Load Cell - Standalone Initialization");

  // Initialize the scale
  scale.begin(HX711_DT, HX711_SCK);

  // Check if the scale is connected properly
  if (scale.is_ready()) {
    Serial.println("HX711 found. Setting up...");
    
    // Set the calibration factor
    scale.set_scale(calibration_factor);
    
    // Tare the scale (reset to 0)
    Serial.println("Taring the scale... Ensure no weight is on it.");
    scale.tare();
    
    Serial.println("Tare complete. Ready to measure.");
  } else {
    Serial.println("HX711 not found. Please check your wiring.");
    while (1); // Halt execution if wiring is wrong
  }
}

void loop() {
  // Check if the HX711 has a new reading available
  if (scale.is_ready()) {
    // Read the weight (average of 5 readings to smooth out noise)
    float weight = scale.get_units(5);
    
    Serial.print("Weight: ");
    Serial.print(weight, 2); // Print with 2 decimal places
    Serial.println(" units");
  } else {
    Serial.println("Error: HX711 not responding.");
  }

  // Small delay to prevent flooding the Serial Monitor
  delay(250); 
}
