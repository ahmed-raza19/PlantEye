#include <WiFi.h>
#include <WebServer.h>

// WiFi credentials
const char* ssid = "YOUR_WIFI_SSID";       // TODO: set your WiFi network name
const char* password = "YOUR_WIFI_PASSWORD";  // TODO: set your WiFi password

// Motor pins (L298N)
#define ENA 2
#define IN1 4
#define IN2 5
#define IN3 18
#define IN4 19
#define ENB 21

// Ultrasonic Sensor Pins
#define TRIG_PIN 12
#define ECHO_PIN 13

int Speed = 4095;          // Max PWM for ESP32
int SAFE_DISTANCE = 20;    // cm
#define SOUND_VELOCITY 0.034

WebServer server(80);

// Store last command for auto-resume
String lastCommand = "stop";

void setup() {
  Serial.begin(115200);

  pinMode(ENA, OUTPUT);
  pinMode(IN1, OUTPUT);
  pinMode(IN2, OUTPUT);
  pinMode(IN3, OUTPUT);
  pinMode(IN4, OUTPUT);
  pinMode(ENB, OUTPUT);

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);

  // WiFi connect
  WiFi.begin(ssid, password);
  Serial.print("Connecting");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nConnected!");
  Serial.println(WiFi.localIP());

  // Web routes
  server.on("/forward", handleForward);
  server.on("/backward", handleBackward);
  server.on("/left", handleLeft);
  server.on("/right", handleRight);
  server.on("/stop", handleStop);
  server.on("/distance", handleDistance);

  server.begin();
}

void loop() {
  server.handleClient();

  float d = getDistance();

  // If obstacle close → stop movement
  if (d > 0 && d < SAFE_DISTANCE) {
    Stop();
    return;
  }

  // If no obstacle → resume last movement
  if (lastCommand == "forward") Forward();
  else if (lastCommand == "backward") Backward();
  else if (lastCommand == "left") Left();
  else if (lastCommand == "right") Right();
  else Stop();
}

// ================= MOTOR FUNCTIONS =================
void Forward() {
  analogWrite(ENA, Speed);
  analogWrite(ENB, Speed);
  digitalWrite(IN1, HIGH);
  digitalWrite(IN2, LOW);
  digitalWrite(IN3, HIGH);
  digitalWrite(IN4, LOW);
}

void Backward() {
  analogWrite(ENA, Speed);
  analogWrite(ENB, Speed);
  digitalWrite(IN1, LOW);
  digitalWrite(IN2, HIGH);
  digitalWrite(IN3, LOW);
  digitalWrite(IN4, HIGH);
}

void Left() {
  analogWrite(ENA, Speed);
  analogWrite(ENB, Speed);
  digitalWrite(IN1, HIGH);
  digitalWrite(IN2, LOW);
  digitalWrite(IN3, LOW);
  digitalWrite(IN4, HIGH);
}

void Right() {
  analogWrite(ENA, Speed);
  analogWrite(ENB, Speed);
  digitalWrite(IN1, LOW);
  digitalWrite(IN2, HIGH);
  digitalWrite(IN3, HIGH);
  digitalWrite(IN4, LOW);
}

void Stop() {
  digitalWrite(IN1, LOW);
  digitalWrite(IN2, LOW);
  digitalWrite(IN3, LOW);
  digitalWrite(IN4, LOW);
}

// ================ ULTRASONIC SENSOR =================
float getDistance() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  long duration = pulseIn(ECHO_PIN, HIGH, 20000); // timeout 20ms
  if (duration == 0) return -1; // No reading

  float distanceCm = duration * SOUND_VELOCITY / 2;
  return distanceCm;
}

// ================ HTTP HANDLERS =================
void handleForward() {
  float d = getDistance();
  if (d > 0 && d < SAFE_DISTANCE) {
    Stop();
    lastCommand = "stop";
    server.send(200, "text/plain", "BLOCKED");
    return;
  }
  Forward();
  lastCommand = "forward";
  server.send(200, "text/plain", "OK");
}

void handleBackward() {
  Backward();
  lastCommand = "backward";
  server.send(200, "text/plain", "OK");
}

void handleLeft() {
  float d = getDistance();
  if (d > 0 && d < SAFE_DISTANCE) {
    Stop();
    lastCommand = "stop";
    server.send(200, "text/plain", "BLOCKED");
    return;
  }
  Left();
  lastCommand = "left";
  server.send(200, "text/plain", "OK");
}

void handleRight() {
  float d = getDistance();
  if (d > 0 && d < SAFE_DISTANCE) {
    Stop();
    lastCommand = "stop";
    server.send(200, "text/plain", "BLOCKED");
    return;
  }
  Right();
  lastCommand = "right";
  server.send(200, "text/plain", "OK");
}

void handleStop() {
  Stop();
  lastCommand = "stop";
  server.send(200, "text/plain", "OK");
}

void handleDistance() {
  float d = getDistance();
  server.send(200, "text/plain", String(d));
}