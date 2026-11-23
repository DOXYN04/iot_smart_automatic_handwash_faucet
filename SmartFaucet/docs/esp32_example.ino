/*
 * CONTOH KODE ESP32 - Smart Automatic Handwash Faucet
 * ---------------------------------------------------
 * Firmware asli tidak disertakan repository ini. Ini hanya contoh integrasi:
 *   - ambil konfigurasi dari GET /api/esp-config tiap 10 detik (X-API-KEY)
 *   - matikan buzzer/LED/pompa sesuai pengaturan teknisi
 *   - pakai anomaly_threshold_seconds sebagai batas anomali nonstop
 *   - kirim status ke POST /api/iot-update (endpoint ini TIDAK butuh login)
 *
 * Library: ArduinoJson 7 (ArduinoJson 6: ganti JsonDocument -> StaticJsonDocument<512>)
 * Komponen: ESP32, sensor tangan (pin 4), buzzer (pin 25), LED (pin 26), relay pompa (pin 27).
 * Sesuaikan pin, logika sensor HIGH/LOW, dan alamat server dengan kondisi nyata.
 */
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

const char* WIFI_SSID = "NAMA_WIFI";
const char* WIFI_PASS = "PASSWORD_WIFI";
const char* SERVER_URL = "http://192.168.1.10:5000";  // tanpa trailing slash
const char* ESP_API_KEY = "sama_dengan_ESP_API_KEY_di_dotenv";

const int HAND_PIN  = 4;
const int BUZZER_PIN = 25;
const int LED_PIN    = 26;
const int PUMP_PIN   = 27;

struct FaucetConfig {
  bool buzzer = true;
  bool led = true;
  bool pump = true;
  int anomalyThreshold = 30;  // fallback; server mengirim nilai sebenarnya
};
FaucetConfig config;

bool serverAllowsPump = true;   // diupdate dari field pump_on respons iot-update
unsigned long lastConfigFetch = 0;
unsigned long lastPost = 0;
unsigned long handSince = 0;

void setup() {
  Serial.begin(115200);
  pinMode(HAND_PIN, INPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(LED_PIN, OUTPUT);
  pinMode(PUMP_PIN, OUTPUT);
  applyOutputs(false, false);

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi terhubung: " + WiFi.localIP().toString());
  fetchConfig();
}

void fetchConfig() {
  if (WiFi.status() != WL_CONNECTED) return;

  HTTPClient http;
  http.begin(String(SERVER_URL) + "/api/esp-config");
  http.addHeader("X-API-KEY", ESP_API_KEY);
  int code = http.GET();

  if (code == 200) {
    JsonDocument doc;
    if (!deserializeJson(doc, http.getString())) {
      config.buzzer = doc["buzzer_enabled"] | true;
      config.led = doc["led_enabled"] | true;
      config.pump = doc["pump_enabled"] | true;
      config.anomalyThreshold = doc["anomaly_threshold_seconds"] | 30;
      Serial.printf("Config: buzzer=%d led=%d pump=%d threshold=%ds\n",
                    config.buzzer, config.led, config.pump, config.anomalyThreshold);
    }
  } else {
    Serial.printf("Gagal ambil config (HTTP %d)\n", code);
  }
  http.end();
}

void postUpdate(const char* state, int duration) {
  if (WiFi.status() != WL_CONNECTED) return;

  HTTPClient http;
  http.begin(String(SERVER_URL) + "/api/iot-update");
  http.addHeader("Content-Type", "application/json");
  String body = "{\"state\":\"" + String(state) + "\",\"duration\":" + String(duration) + "}";
  int code = http.POST(body);

  if (code == 200) {
    JsonDocument response;
    if (!deserializeJson(response, http.getString())) {
      // Server sudah memastikan pump_on = false bila pump_enabled = false.
      serverAllowsPump = response["pump_on"] | false;
    }
  } else {
    Serial.printf("Gagal kirim update (HTTP %d)\n", code);
  }
  http.end();
}

void applyOutputs(bool handDetected, bool anomaly) {
  // Kunci semua output pada pengaturan teknisi.
  digitalWrite(BUZZER_PIN, (config.buzzer && anomaly) ? HIGH : LOW);
  digitalWrite(LED_PIN, (config.led && (handDetected || anomaly)) ? HIGH : LOW);
  digitalWrite(PUMP_PIN, (config.pump && serverAllowsPump && handDetected && !anomaly) ? HIGH : LOW);
}

void loop() {
  if (millis() - lastConfigFetch >= 10000) {
    fetchConfig();
    lastConfigFetch = millis();
  }

  bool handDetected = digitalRead(HAND_PIN) == HIGH;
  if (handDetected && handSince == 0) handSince = millis();
  if (!handDetected) handSince = 0;

  int duration = handSince ? (millis() - handSince) / 1000 : 0;
  bool anomaly = handDetected && duration >= config.anomalyThreshold;

  applyOutputs(handDetected, anomaly);

  // Kirim perubahan status (±1 detik), bukan tiap loop.
  if (millis() - lastPost >= 1000) {
    const char* state = anomaly ? "anomaly" : (handDetected ? "active" : "idle");
    postUpdate(state, handDetected ? duration : 0);
    lastPost = millis();
  }
}
