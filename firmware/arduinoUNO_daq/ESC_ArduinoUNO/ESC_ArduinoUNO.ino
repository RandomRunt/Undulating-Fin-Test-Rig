#include <Servo.h>

Servo bldcESC;
// Brown wire - GND
// Orange wire - 5V
const int escPin = 9; // Yellow wire
const int neutralSignal = 1500; 

// The borrowed helper function to clean up the loop
void writeUsAndWait(const int pulseUs, const uint32_t holdMs) {
  bldcESC.writeMicroseconds(pulseUs);
  delay(holdMs);
}

void setup() {
  Serial.begin(115200);

  // The Uno handles timers automatically; just attach with the min/max pulse
  bldcESC.attach(escPin, 1000, 2000);

  Serial.println("Sending 5V neutral signal to arm ESC...");
  writeUsAndWait(neutralSignal, 4000); // Hold 1500us for 4 seconds to arm
  
  Serial.println("ESC initialized.");
}

void loop() {
  // Drives Better this way!
  Serial.println("Driving Forward...");
  writeUsAndWait(1300, 3000);

  Serial.println("Returning to Neutral...");
  writeUsAndWait(neutralSignal, 2000);

  Serial.println("Driving Reverse...");
  writeUsAndWait(1700, 3000);

  Serial.println("Returning to Neutral...");
  writeUsAndWait(neutralSignal, 4000);
}
