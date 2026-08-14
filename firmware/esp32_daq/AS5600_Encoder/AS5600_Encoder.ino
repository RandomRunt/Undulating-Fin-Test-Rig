#include <Wire.h>

// AS5600 I2C Address is fixed at 0x36
#define AS5600_ADDRESS 0x36

// The raw angle is split across two registers: 0x0C (high byte) and 0x0D (low byte)
#define RAW_ANGLE_REGISTER 0x0C 

void setup() {
  // Initialize Serial Monitor
  Serial.begin(115200);
  while (!Serial) { delay(10); }

  // Initialize I2C (SDA = 21, SCL = 22)
  Wire.begin(21, 22); 
  
  Serial.println("Starting AS5600 I2C Test...");
  
  // Quick I2C scanner check to verify connection
  Wire.beginTransmission(AS5600_ADDRESS);
  if (Wire.endTransmission() == 0) {
    Serial.println("AS5600 successfully detected!");
  } else {
    Serial.println("Error: AS5600 not found. Check wiring.");
  }
}

void loop() {
  // Point to the register we want to read from
  Wire.beginTransmission(AS5600_ADDRESS);
  Wire.write(RAW_ANGLE_REGISTER);
  Wire.endTransmission(false); // Send a restart condition
  
  // Request 2 bytes of data (High Byte and Low Byte)
  Wire.requestFrom(AS5600_ADDRESS, 2); 

  if (Wire.available() >= 2) {
    uint8_t highByte = Wire.read();
    uint8_t lowByte = Wire.read();
    
    // Combine the two bytes into a 12-bit number
    // The high byte only contains the 4 highest bits (masking with 0x0F)
    uint16_t rawAngle = ((highByte & 0x0F) << 8) | lowByte;
    
    // Convert the 12-bit raw value (0 - 4095) to degrees (0 - 360)
    float degrees = (rawAngle / 4096.0) * 360.0;
    
    // Print the results to the Serial Monitor
    Serial.print("Raw Value: ");
    Serial.print(rawAngle);
    Serial.print(" \t Angle: ");
    Serial.print(degrees, 2);
    Serial.println(" °");
  } else {
    Serial.println("Failed to read data.");
  }

  // Brief delay to make the Serial Monitor readable
  delay(100); 
}
