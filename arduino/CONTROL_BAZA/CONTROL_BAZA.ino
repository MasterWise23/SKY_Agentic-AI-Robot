#include <SoftwareSerial.h>

// ── Bluetooth (HC-05) ──────────────────
// Using Serial1 on Mega (pins 18=TX, 19=RX)

// ── Base Motors ────────────────────────
const int ENA = 2;   // Left side speed (PWM)
const int IN1 = 22;  // Left side direction
const int IN2 = 23;
const int ENB = 3;   // Right side speed (PWM)
const int IN3 = 24;  // Right side direction
const int IN4 = 25;

// ── Speed ──────────────────────────────
int leftSpeed  = 200;
int rightSpeed = 200;

// ── Incoming command ───────────────────
String incoming = "";

void setup() {
  Serial.begin(9600);
  Serial1.begin(9600); // HC-05 on pins 18(TX) 19(RX)

  // Motor pins
  pinMode(ENA, OUTPUT);
  pinMode(IN1, OUTPUT);
  pinMode(IN2, OUTPUT);
  pinMode(ENB, OUTPUT);
  pinMode(IN3, OUTPUT);
  pinMode(IN4, OUTPUT);

  stopBase();
  Serial.println("Robot ready!");
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
}

void handleCommand(String cmd) {
  if      (cmd == "MOVE:F") moveForward();
  else if (cmd == "MOVE:B") moveBack();
  else if (cmd == "MOVE:L") moveLeft();
  else if (cmd == "MOVE:R") moveRight();
  else if (cmd == "MOVE:S") stopBase();
  else if (cmd.startsWith("SPD:")) parseSpeed(cmd.substring(4));
  else if (cmd.startsWith("ARM:")) Serial.println("ARM command received");
  else if (cmd == "BAT:?")  sendBattery();
}

// ── Movement ───────────────────────────

void moveForward() {
  // Left side forward
  analogWrite(ENA, leftSpeed);
  digitalWrite(IN1, HIGH);
  digitalWrite(IN2, LOW);
  // Right side forward
  analogWrite(ENB, rightSpeed);
  digitalWrite(IN3, HIGH);
  digitalWrite(IN4, LOW);
  Serial.println("Moving FORWARD");
}

void moveBack() {
  // Left side backward
  analogWrite(ENA, leftSpeed);
  digitalWrite(IN1, LOW);
  digitalWrite(IN2, HIGH);
  // Right side backward
  analogWrite(ENB, rightSpeed);
  digitalWrite(IN3, LOW);
  digitalWrite(IN4, HIGH);
  Serial.println("Moving BACK");
}

void moveLeft() {
  // Left side backward
  analogWrite(ENA, leftSpeed);
  digitalWrite(IN1, LOW);
  digitalWrite(IN2, HIGH);
  // Right side forward
  analogWrite(ENB, rightSpeed);
  digitalWrite(IN3, HIGH);
  digitalWrite(IN4, LOW);
  Serial.println("Moving LEFT");
}

void moveRight() {
  // Left side forward
  analogWrite(ENA, leftSpeed);
  digitalWrite(IN1, HIGH);
  digitalWrite(IN2, LOW);
  // Right side backward
  analogWrite(ENB, rightSpeed);
  digitalWrite(IN3, LOW);
  digitalWrite(IN4, HIGH);
  Serial.println("Moving RIGHT");
}

void stopBase() {
  analogWrite(ENA, 0);
  analogWrite(ENB, 0);
  digitalWrite(IN1, LOW);
  digitalWrite(IN2, LOW);
  digitalWrite(IN3, LOW);
  digitalWrite(IN4, LOW);
  Serial.println("STOP");
}

// ── Speed control ──────────────────────
// App sends: "SPD:200" for both sides
// or "SPD:150,200" for left,right individually

void parseSpeed(String data) {
  int comma = data.indexOf(',');
  if (comma == -1) {
    // Same speed for both sides
    int spd = constrain(data.toInt(), 0, 255);
    leftSpeed  = spd;
    rightSpeed = spd;
    Serial.println("Speed set to: " + String(spd));
  } else {
    // Individual speeds
    leftSpeed  = constrain(data.substring(0, comma).toInt(), 0, 255);
    rightSpeed = constrain(data.substring(comma + 1).toInt(), 0, 255);
    Serial.println("Left: " + String(leftSpeed) + " Right: " + String(rightSpeed));
  }
}

// ── Battery ────────────────────────────
void sendBattery() {
  int raw = analogRead(A0);
  int percent = map(raw, 600, 1023, 0, 100);
  percent = constrain(percent, 0, 100);
  Serial1.println("BAT:" + String(percent));
  Serial.println("Battery: " + String(percent) + "%");
}