#include <WiFi.h>
#include <HTTPClient.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>
#include <ArduinoJson.h>
#include <SPI.h>

// ============================================
// PINI CORECTI pentru Ideaspark ESP32 1.14"
// ============================================
#define TFT_CS   15
#define TFT_RST   4
#define TFT_DC    2
#define TFT_BL   32

// ============================================
// CONFIGURARE WIFI & SERVER
// ============================================
const char* WIFI_SSID = "Taylor Swift";
const char* WIFI_PASS = "razadesoare.916";
const char* SERVER_IP = "172.16.0.172";
const int   SERVER_PORT = 5000;
const bool  IS_LEFT_EYE = false; //pt ochiu stang vine = true;

// ============================================
// CULORI
// ============================================
#define COLOR_NEGRU    ST77XX_BLACK
#define COLOR_ALB      ST77XX_WHITE
#define COLOR_FERICIT  ST77XX_GREEN
#define COLOR_TRIST    ST77XX_BLUE
#define COLOR_FURIOS   ST77XX_RED
#define COLOR_SURPRINS ST77XX_YELLOW
#define COLOR_NEUTRU   0x07FF  // Cyan

Adafruit_ST7789 tft = Adafruit_ST7789(TFT_CS, TFT_DC, TFT_RST);

String currentEmotion = "neutral";
String lastEmotion = "";

// ============================================
// DESENARE OCHI
// ============================================
void drawEye(String emotion) {
  tft.fillScreen(COLOR_NEGRU);

  int cx = 135 / 2;  // 67
  int cy = 240 / 2;  // 120

  uint16_t irisColor;

  if (emotion == "happy") {
    irisColor = COLOR_FERICIT;
    tft.fillCircle(cx, cy, 45, COLOR_ALB);
    tft.fillCircle(cx, cy, 35, irisColor);
    tft.fillCircle(cx, cy, 15, COLOR_NEGRU);
    tft.fillRect(cx - 50, cy + 10, 100, 50, COLOR_NEGRU);
    tft.fillRoundRect(cx - 40, cy - 60, 80, 10, 5, COLOR_ALB);

  } else if (emotion == "sad") {
    irisColor = COLOR_TRIST;
    tft.fillCircle(cx, cy, 40, COLOR_ALB);
    tft.fillCircle(cx, cy, 28, irisColor);
    tft.fillCircle(cx, cy, 12, COLOR_NEGRU);
    tft.fillRect(cx - 50, cy - 45, 100, 25, COLOR_NEGRU);
    if (IS_LEFT_EYE) {
      tft.fillTriangle(cx - 40, cy - 55, cx + 40, cy - 65, cx + 40, cy - 50, COLOR_ALB);
    } else {
      tft.fillTriangle(cx + 40, cy - 55, cx - 40, cy - 65, cx - 40, cy - 50, COLOR_ALB);
    }

  } else if (emotion == "angry") {
    irisColor = COLOR_FURIOS;
    tft.fillCircle(cx, cy, 42, COLOR_ALB);
    tft.fillCircle(cx, cy, 30, irisColor);
    tft.fillCircle(cx, cy, 12, COLOR_NEGRU);
    if (IS_LEFT_EYE) {
      tft.fillTriangle(cx - 40, cy - 50, cx + 40, cy - 65, cx + 40, cy - 50, COLOR_FURIOS);
    } else {
      tft.fillTriangle(cx + 40, cy - 50, cx - 40, cy - 65, cx - 40, cy - 50, COLOR_FURIOS);
    }

  } else if (emotion == "surprise") {
    irisColor = COLOR_SURPRINS;
    tft.fillCircle(cx, cy, 50, COLOR_ALB);
    tft.fillCircle(cx, cy, 38, irisColor);
    tft.fillCircle(cx, cy, 18, COLOR_NEGRU);
    tft.fillCircle(cx, cy, 8, COLOR_ALB);
    tft.fillRoundRect(cx - 42, cy - 75, 84, 12, 6, COLOR_ALB);

  } else {
    // NEUTRU
    irisColor = COLOR_NEUTRU;
    tft.fillCircle(cx, cy, 42, COLOR_ALB);
    tft.fillCircle(cx, cy, 30, irisColor);
    tft.fillCircle(cx, cy, 12, COLOR_NEGRU);
    tft.fillCircle(cx + 12, cy - 12, 7, COLOR_ALB);
    tft.fillRoundRect(cx - 38, cy - 58, 76, 8, 4, COLOR_ALB);
  }

  // Reflexie lumina
  if (emotion != "surprise") {
    tft.fillCircle(cx + 12, cy - 12, 6, COLOR_ALB);
  }

  // Text emotie
  tft.setTextColor(COLOR_ALB);
  tft.setTextSize(1);
  tft.setCursor(5, 225);
  tft.print(IS_LEFT_EYE ? "L:" : "R:");
  tft.print(emotion);
}

void blinkAnimation() {
  int cx = 135 / 2;
  int cy = 240 / 2;
  tft.fillRect(cx - 50, cy - 50, 100, 100, COLOR_NEGRU);
  delay(80);
  drawEye(currentEmotion);
}

// ============================================
// WIFI
// ============================================
void connectWiFi() {
  tft.fillScreen(COLOR_NEGRU);
  tft.setTextColor(COLOR_ALB);
  tft.setTextSize(1);
  tft.setCursor(10, 110);
  tft.print("Connecting WiFi...");

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    attempts++;
  }

  tft.fillScreen(COLOR_NEGRU);
  tft.setCursor(10, 110);
  if (WiFi.status() == WL_CONNECTED) {
    tft.setTextColor(COLOR_FERICIT);
    tft.print("WiFi OK!");
    tft.setCursor(10, 125);
    tft.setTextColor(COLOR_ALB);
    tft.print(WiFi.localIP());
    delay(1500);
  } else {
    tft.setTextColor(COLOR_FURIOS);
    tft.print("WiFi FAILED!");
    delay(2000);
  }
}

String getEmotionFromServer() {
  if (WiFi.status() != WL_CONNECTED) return currentEmotion;

  HTTPClient http;
  String url = "http://" + String(SERVER_IP) + ":" + String(SERVER_PORT) + "/emotion";
  http.begin(url);
  http.setTimeout(3000);

  int code = http.GET();
  if (code == 200) {
    String payload = http.getString();
    StaticJsonDocument<128> doc;
    deserializeJson(doc, payload);
    String emotion = doc["emotion"].as<String>();
    http.end();
    return emotion;
  }
  http.end();
  return currentEmotion;
}

// ============================================
// SETUP & LOOP
// ============================================
void setup() {
  Serial.begin(115200);

  pinMode(TFT_BL, OUTPUT);
  digitalWrite(TFT_BL, HIGH);

  tft.init(135, 240);
  tft.setRotation(2);
  tft.fillScreen(COLOR_NEGRU);

  connectWiFi();
  drawEye("neutral");
}

unsigned long lastCheck = 0;
unsigned long lastBlink = 0;
int blinkInterval = 4000;

void loop() {
  unsigned long now = millis();

  if (now - lastBlink > blinkInterval) {
    blinkAnimation();
    lastBlink = now;
    blinkInterval = random(3000, 7000);
  }

  if (now - lastCheck > 2000) {
    String emotion = getEmotionFromServer();
    if (emotion != lastEmotion) {
      currentEmotion = emotion;
      lastEmotion = emotion;
      drawEye(emotion);
    }
    lastCheck = now;
  }
}
