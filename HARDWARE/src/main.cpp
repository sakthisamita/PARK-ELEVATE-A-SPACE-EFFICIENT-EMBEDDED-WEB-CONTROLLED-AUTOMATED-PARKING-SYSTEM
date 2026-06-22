#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <ArduinoJson.h>

/* ─── Pin Definitions ─────────────────────────────────────────────────────── */
#define PIN_ENA   5    // PWM speed control
#define PIN_IN1   18   // direction bit 1
#define PIN_IN2   19   // direction bit 2

/* ─── Motor Calibration ───────────────────────────────────────────────────── */
#define MOTOR_SPEED  80          // 0-255 PWM duty (ENA)
#define STEP_MS      175       // ms for one 90° step — CALIBRATE THIS
#define SETTLE_MS    300          // brief pause after each step

/* ─── Carousel Constants ──────────────────────────────────────────────────── */
#define TOTAL_SLOTS  4
const char* SLOT_NAMES[] = {"A", "B", "C", "D"};

/* ─── Wi-Fi AP Config ─────────────────────────────────────────────────────── */
const char* AP_SSID     = "Park_Elevate";
const char* AP_PASSWORD = "parking123";
const IPAddress AP_IP(192, 168, 4, 1);
const IPAddress AP_GW(192, 168, 4, 1);
const IPAddress AP_SUBNET(255, 255, 255, 0);

/* ─── State ───────────────────────────────────────────────────────────────── */
volatile int  carouselPos = 0;   // slot index currently at Entry/Exit (0–3)
volatile bool isBusy      = false;

WebServer server(80);

/* ══════════════════════════════════════════════════════════════════════════
   Motor Control
   ══════════════════════════════════════════════════════════════════════════ */

void motorStop() {
  digitalWrite(PIN_IN1, LOW);
  digitalWrite(PIN_IN2, LOW);
  analogWrite(PIN_ENA, 0);
}

void motorCW() {
  // IN1=HIGH, IN2=LOW → Clockwise
  digitalWrite(PIN_IN1, HIGH);
  digitalWrite(PIN_IN2, LOW);
  analogWrite(PIN_ENA, MOTOR_SPEED);
}

void motorCCW() {
  // IN1=LOW, IN2=HIGH → Counter-clockwise
  digitalWrite(PIN_IN1, LOW);
  digitalWrite(PIN_IN2, HIGH);
  analogWrite(PIN_ENA, MOTOR_SPEED);
}

/**
 * Rotate the carousel N steps (each = 90°) in the given direction.
 * Blocking call — server is paused during rotation.
 *
 * @param steps     Number of 90° increments (1–3)
 * @param clockwise true = CW, false = CCW
 */
void rotateCarousel(int steps, bool clockwise) {
  if (steps <= 0 || steps >= TOTAL_SLOTS) return;

  isBusy = true;

  for (int i = 0; i < steps; i++) {
    if (clockwise) {
      motorCW();
      delay(STEP_MS);
      motorStop();
      // Update tracked position
      carouselPos = (carouselPos + 1) % TOTAL_SLOTS;
    } else {
      motorCCW();
      delay(STEP_MS);
      motorStop();
      carouselPos = (carouselPos - 1 + TOTAL_SLOTS) % TOTAL_SLOTS;
    }
    delay(SETTLE_MS);   // mechanical settle time between steps
  }

  isBusy = false;
}

/* ══════════════════════════════════════════════════════════════════════════
   HTTP Handlers
   ══════════════════════════════════════════════════════════════════════════ */

void sendCORSHeaders() {
  server.sendHeader("Access-Control-Allow-Origin",  "*");
  server.sendHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  server.sendHeader("Access-Control-Allow-Headers", "Content-Type");
}

/* GET /health ─────────────────────────────────────────────────────────────── */
void handleHealth() {
  sendCORSHeaders();
  StaticJsonDocument<64> doc;
  doc["ok"]    = true;
  doc["uptime"] = millis() / 1000;
  String body;
  serializeJson(doc, body);
  server.send(200, "application/json", body);
}

/* GET /status ─────────────────────────────────────────────────────────────── */
void handleStatus() {
  sendCORSHeaders();
  StaticJsonDocument<128> doc;
  doc["position"]      = carouselPos;
  doc["slot_at_entry"] = SLOT_NAMES[carouselPos];
  doc["busy"]          = isBusy;
  doc["uptime_s"]      = millis() / 1000;
  String body;
  serializeJson(doc, body);
  server.send(200, "application/json", body);
}

/* GET /rotate?steps=N&dir=CW|CCW ──────────────────────────────────────────── */
void handleRotate() {
  sendCORSHeaders();

  if (isBusy) {
    server.send(503, "application/json", "{\"error\":\"Motor busy\"}");
    return;
  }

  // Parse query params
  if (!server.hasArg("steps") || !server.hasArg("dir")) {
    server.send(400, "application/json", "{\"error\":\"Missing steps or dir param\"}");
    return;
  }

  int  steps     = server.arg("steps").toInt();
  bool clockwise = (server.arg("dir") == "CW");

  if (steps < 0 || steps > 3) {
    server.send(400, "application/json", "{\"error\":\"steps must be 0-3\"}");
    return;
  }

  // Record position before rotation for response
  int prevPos = carouselPos;

  // Perform rotation (blocking)
  rotateCarousel(steps, clockwise);

  // Build response
  StaticJsonDocument<128> doc;
  doc["success"]    = true;
  doc["steps"]      = steps;
  doc["direction"]  = clockwise ? "CW" : "CCW";
  doc["prev_slot"]  = SLOT_NAMES[prevPos];
  doc["curr_slot"]  = SLOT_NAMES[carouselPos];
  doc["position"]   = carouselPos;
  String body;
  serializeJson(doc, body);
  server.send(200, "application/json", body);
}

/* OPTIONS preflight ─────────────────────────────────────────────────────── */
void handleOptions() {
  sendCORSHeaders();
  server.send(204);
}

/* 404 catch-all ─────────────────────────────────────────────────────────── */
void handleNotFound() {
  server.send(404, "application/json", "{\"error\":\"Not found\"}");
}

/* ══════════════════════════════════════════════════════════════════════════
   Setup
   ══════════════════════════════════════════════════════════════════════════ */
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("\n[CarouselPark] Booting…");

  /* ── GPIO Init ───────────────────────────────────────────────────────── */
  pinMode(PIN_ENA, OUTPUT);
  pinMode(PIN_IN1, OUTPUT);
  pinMode(PIN_IN2, OUTPUT);
  motorStop();   // ensure motor is off at startup

  /* ── Soft AP ─────────────────────────────────────────────────────────── */
  WiFi.mode(WIFI_AP);
  WiFi.softAPConfig(AP_IP, AP_GW, AP_SUBNET);
  WiFi.softAP(AP_SSID, AP_PASSWORD);
  Serial.printf("[WiFi] AP started: SSID=%s  IP=%s\n",
                AP_SSID, WiFi.softAPIP().toString().c_str());

  /* ── HTTP Routes ─────────────────────────────────────────────────────── */
  server.on("/health",  HTTP_GET,     handleHealth);
  server.on("/status",  HTTP_GET,     handleStatus);
  server.on("/rotate",  HTTP_GET,     handleRotate);
  server.on("/rotate",  HTTP_OPTIONS, handleOptions);
  server.onNotFound(handleNotFound);
  server.begin();
  Serial.println("[HTTP] Server started on port 80");

  /* ── Self-test blink ─────────────────────────────────────────────────── */
  Serial.println("[Motor] Self-test: brief CW pulse…");
  motorCW();  delay(200);  motorStop();
  Serial.println("[Boot] Ready. Slot A at Entry/Exit.");
}

/* ══════════════════════════════════════════════════════════════════════════
   Loop
   ══════════════════════════════════════════════════════════════════════════ */
void loop() {
  server.handleClient();
  // Yield for Wi-Fi stack
  delay(1);
}
