#include <Wire.h>
#include <Adafruit_INA260.h>
#include <HX711.h>
#include <Servo.h>

// --- Pin Definitions ---
const int HX711_DT = 4;
const int HX711_SCK = 5;
const int ESC_PIN = 9;

// --- Objects ---
Adafruit_INA260 ina260 = Adafruit_INA260();
HX711 scale;
Servo esc;

// --- ESC Configuration ---
// For bidirectional ESCs: 1500us is neutral (stop), 1000us is full reverse, 2000us is full forward.
const int ESC_NEUTRAL = 1500;
const int ESC_MIN = 1000;
const int ESC_MAX = 2000;
int current_pwm = ESC_NEUTRAL;

// --- Timing Variables ---
unsigned long previousMillis = 0;
const long interval = 500; // Print data every 500ms

void setup() {
  Serial.begin(115200);
  while (!Serial) { delay(10); } // Wait for serial console
  Serial.println("System Initialization Starting...");

  // 1. Initialize INA260
  if (!ina260.begin()) {
    Serial.println("Couldn't find INA260 chip. Check wiring!");
    while (1); // Halt execution
  }
  Serial.println("INA260 Found.");

  // 2. Initialize HX711
  scale.begin(HX711_DT, HX711_SCK);
  // NOTE: You must calibrate your load cell to find this value. 
  // Read raw values first with a known weight, then set this factor.
  scale.set_scale(2280.f); 
  scale.tare(); // Reset the scale to 0
  Serial.println("HX711 Initialized and Tared.");

  // 3. Initialize and Arm ESC
  esc.attach(ESC_PIN, ESC_MIN, ESC_MAX);
  Serial.println("Arming ESC... Ensure motor area is clear.");
  
  // Bidirectional ESCs usually arm by receiving the neutral signal (1500us)
  esc.writeMicroseconds(ESC_NEUTRAL);
  delay(3000); // Wait 3 seconds for the ESC to beep and arm
  Serial.println("ESC Armed.");
  
  Serial.println("\n--- Setup Complete ---");
  Serial.println("Send a value between 1000 and 2000 in the Serial Monitor to control the ESC.");
  Serial.println("1500 = Stop | >1500 = Forward | <1500 = Reverse");
}

void loop() {
  // --- 1. Handle Serial Input for ESC Control ---
  if (Serial.available() > 0) {
    int input = Serial.parseInt();
    
    // Clear the rest of the buffer (handles newline characters)
    while(Serial.available() > 0) {
      Serial.read();
    }

    if (input >= ESC_MIN && input <= ESC_MAX) {
      current_pwm = input;
      esc.writeMicroseconds(current_pwm);
      Serial.print(">>> ESC PWM Set to: ");
      Serial.println(current_pwm);
    } else if (input != 0) { // Ignore the 0 parsed from stray newlines
      Serial.println("Invalid Input. Enter a value between 1000 and 2000.");
    }
  }

  // --- 2. Read and Print Sensor Data Non-Blockingly ---
  unsigned long currentMillis = millis();
  if (currentMillis - previousMillis >= interval) {
    previousMillis = currentMillis;

    // Read INA260
    float voltage_mV = ina260.readBusVoltage();
    float current_mA = ina260.readCurrent();
    float power_mW   = ina260.readPower();

    // Read HX711
    float weight = 0.0;
    if (scale.is_ready()) {
      weight = scale.get_units(5); // Average of 5 readings
    } else {
      Serial.println("HX711 not ready.");
    }

    // Print Data
    Serial.print("ESC PWM: "); Serial.print(current_pwm);
    Serial.print(" | Volts (V): "); Serial.print(voltage_mV / 1000.0, 2);
    Serial.print(" | Amps (A): "); Serial.print(current_mA / 1000.0, 2);
    Serial.print(" | Power (W): "); Serial.print(power_mW / 1000.0, 2);
    Serial.print(" | Weight: "); Serial.println(weight, 2);
  }
}
