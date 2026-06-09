#include <Servo.h>

Servo myServo;
String incoming = "";
int currentAngle = 90;

void setup() {
  Serial.begin(9600);
  Serial1.begin(9600);
  myServo.attach(9, 544, 2400);
  myServo.writeMicroseconds(1472);
  Serial.println("Ready!");
}

void loop() {
  while (Serial1.available()) {
    char c = Serial1.read();
    if (c == '\n') {
      incoming.trim();
      if (incoming.length() > 0) {
        Serial.println("Received: " + incoming);
        handleCommand(incoming);
        incoming = "";
      }
    } else {
      incoming += c;
    }
  }
  
  // Keep servo active
  if (myServo.attached()) {
    myServo.writeMicroseconds(map(currentAngle, 0, 360, 544, 2400));
  }
}

void handleCommand(String cmd) {
  if (cmd.startsWith("ARM:")) parseArm(cmd.substring(4));
  else if (cmd == "BAT:?") Serial1.println("BAT:100");
}

void parseArm(String data) {
  int comma = data.indexOf(',');
  String part = (comma == -1) ? data : data.substring(0, comma);
  currentAngle = constrain(part.toInt(), 0, 360);
  int micros = map(currentAngle, 0, 360, 544, 2400);
  myServo.writeMicroseconds(micros);
  Serial.println("Servo → " + String(currentAngle) + "°");
}