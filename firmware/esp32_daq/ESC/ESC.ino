#include <ESP32Servo.h>

Servo bldcESC;
const int escPin = 18; 

// FINE-TUNING NEUTRAL: If the motor spins slowly on startup, 
// adjust this number slightly (e.g., between 1490 and 1510) until it completely stops.
const int neutralSignal = 1500; 

void setup() {
  Serial.begin(115200);

  ESP32PWM::allocateTimer(0);
  ESP32PWM::allocateTimer(1);

  bldcESC.setPeriodHertz(50); 
  bldcESC.attach(escPin, 1000, 2000);

  // Mandatory step: ESC will not arm unless signal is dead-center on boot
  Serial.println("Sending neutral signal to arm ESC...");
  bldcESC.writeMicroseconds(neutralSignal); 
  
  // Give the ESC 4 seconds to recognize the neutral position and initialize
  delay(4000); 
  Serial.println("ESC initialized.");
}

void loop() {
  // Test Sequence: Forward -> Stop -> Reverse -> Stop
  
  Serial.println("Driving Forward...");
  bldcESC.writeMicroseconds(1750); // Safe low-speed forward
  delay(3000);

  Serial.println("Returning to Neutral...");
  bldcESC.writeMicroseconds(neutralSignal); 
  delay(2000);

  Serial.println("Driving Reverse...");
  bldcESC.writeMicroseconds(1250); // Safe low-speed reverse (1:1 power ratio)
  delay(3000);

  Serial.println("Returning to Neutral...");
  bldcESC.writeMicroseconds(neutralSignal); 
  delay(4000);
}
