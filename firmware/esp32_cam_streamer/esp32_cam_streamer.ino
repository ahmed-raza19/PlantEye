#include <WiFi.h>
#include <PubSubClient.h>
#include "esp_camera.h"
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"

// ===========================
// WiFi Credentials
// ===========================
const char* ssid = "YOUR_WIFI_SSID";       // TODO: set your WiFi network name
const char* password = "YOUR_WIFI_PASSWORD";  // TODO: set your WiFi password

// ===========================
// MQTT Broker Settings
// ===========================
const char* mqtt_server = "192.168.1.100";  // TODO: set to your MQTT broker's local IP
const int mqtt_port = 1883;
const char* mqtt_user = "";
const char* mqtt_pass = "";

// MQTT Topics
const char* topic_image = "planteye/camera/image";
const char* topic_command = "planteye/camera/command";
const char* topic_status = "planteye/camera/status";
const char* topic_stream = "planteye/camera/stream";

// ===========================
// Camera Pins (AI-Thinker)
// ===========================
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22
#define FLASH_GPIO_NUM     4

WiFiClient espClient;
PubSubClient mqtt(espClient);

bool streamingActive = false;
unsigned long lastStreamTime = 0;
const int streamInterval = 200;  // Slower: 200ms = 5 FPS
unsigned long lastReconnect = 0;
int failedPublishes = 0;
int successfulFrames = 0;

void setup_camera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  
  // Smaller, more compressed images for MQTT
  config.frame_size = FRAMESIZE_HVGA;  // 480x320 - smaller than VGA
  config.jpeg_quality = 20;  // Higher number = more compression = smaller size
  config.fb_count = 1;
  config.grab_mode = CAMERA_GRAB_LATEST;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed: 0x%x\n", err);
    delay(1000);
    ESP.restart();
  }
  
  // Optimize sensor settings for smaller file size
  sensor_t * s = esp_camera_sensor_get();
  if (s != NULL) {
    s->set_brightness(s, 0);
    s->set_contrast(s, 0);
    s->set_saturation(s, -1);  // Reduce saturation = smaller file
    s->set_whitebal(s, 1);
    s->set_awb_gain(s, 1);
    s->set_wb_mode(s, 0);
    s->set_exposure_ctrl(s, 1);
    s->set_aec2(s, 0);
    s->set_ae_level(s, 0);
    s->set_aec_value(s, 300);
    s->set_gain_ctrl(s, 1);
    s->set_agc_gain(s, 0);
    s->set_gainceiling(s, (gainceiling_t)0);
    s->set_bpc(s, 0);
    s->set_wpc(s, 1);
    s->set_raw_gma(s, 1);
    s->set_lenc(s, 1);
    s->set_hmirror(s, 0);
    s->set_vflip(s, 0);
    s->set_dcw(s, 1);
    s->set_colorbar(s, 0);
  }
  
  Serial.println("✓ Camera initialized (HVGA 480x320, Quality 20)");
}

void callback(char* topic, byte* payload, unsigned int length) {
  String message;
  for (int i = 0; i < length; i++) {
    message += (char)payload[i];
  }
  
  Serial.println("Command received: " + message);
  
  if (String(topic) == topic_command) {
    if (message == "CAPTURE") {
      captureAndSend();
    }
    else if (message == "START_STREAM") {
      streamingActive = true;
      failedPublishes = 0;
      successfulFrames = 0;
      mqtt.publish(topic_status, "Streaming started", true);
      Serial.println("✓ Streaming started");
    }
    else if (message == "STOP_STREAM") {
      streamingActive = false;
      mqtt.publish(topic_status, "Streaming stopped", true);
      Serial.printf("✓ Streaming stopped (Success: %d, Failed: %d)\n", successfulFrames, failedPublishes);
    }
    else if (message == "FLASH_ON") {
      digitalWrite(FLASH_GPIO_NUM, HIGH);
      mqtt.publish(topic_status, "Flash ON", true);
    }
    else if (message == "FLASH_OFF") {
      digitalWrite(FLASH_GPIO_NUM, LOW);
      mqtt.publish(topic_status, "Flash OFF", true);
    }
  }
}

bool publishWithRetry(const char* topic, const char* payload, int retries = 3) {
  for (int i = 0; i < retries; i++) {
    if (mqtt.publish(topic, payload, false)) {
      return true;
    }
    delay(50);
    mqtt.loop();
  }
  return false;
}

bool publishWithRetry(const char* topic, const uint8_t* payload, unsigned int length, int retries = 3) {
  for (int i = 0; i < retries; i++) {
    if (mqtt.publish(topic, payload, length, false)) {
      return true;
    }
    delay(50);
    mqtt.loop();
  }
  return false;
}

void captureAndSend() {
  camera_fb_t * fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("Camera capture failed");
    mqtt.publish(topic_status, "Capture failed");
    return;
  }

  Serial.printf("Captured image: %d bytes\n", fb->len);
  
  // Smaller chunks for reliability
  const int chunkSize = 1024;  // 1KB chunks
  int chunks = (fb->len + chunkSize - 1) / chunkSize;
  
  // Send metadata
  char metadata[100];
  sprintf(metadata, "START:%d:%d", fb->len, chunks);
  
  if (!publishWithRetry(topic_image, metadata)) {
    Serial.println("Failed to send capture header");
    esp_camera_fb_return(fb);
    return;
  }
  
  delay(100);
  
  // Send image in chunks
  bool success = true;
  for (int i = 0; i < chunks; i++) {
    int offset = i * chunkSize;
    int len = min(chunkSize, (int)(fb->len - offset));
    
    if (!publishWithRetry(topic_image, fb->buf + offset, len)) {
      Serial.printf("Failed chunk %d/%d\n", i + 1, chunks);
      success = false;
      break;
    }
    
    if (i % 10 == 0) {
      Serial.printf("Sent chunk %d/%d\n", i + 1, chunks);
    }
    
    delay(30);
    mqtt.loop();
  }
  
  if (success) {
    publishWithRetry(topic_image, "END");
    Serial.println("✓ Image sent");
  }
  
  esp_camera_fb_return(fb);
}

void sendStreamFrame() {
  if (!streamingActive) return;
  
  // Don't send if not connected
  if (!mqtt.connected()) {
    Serial.println("MQTT disconnected, skipping frame");
    return;
  }
  
  if (millis() - lastStreamTime < streamInterval) return;
  lastStreamTime = millis();
  
  camera_fb_t * fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("Stream frame capture failed");
    failedPublishes++;
    return;
  }

  // If image is too large, skip this frame
  if (fb->len > 50000) {  // More than 50KB
    Serial.printf("Frame too large (%d bytes), skipping\n", fb->len);
    esp_camera_fb_return(fb);
    failedPublishes++;
    return;
  }

  // Very small chunks for streaming
  const int chunkSize = 1024;  // 1KB chunks
  int chunks = (fb->len + chunkSize - 1) / chunkSize;
  
  // Send header with retry
  char header[50];
  sprintf(header, "FRAME:%d:%d", fb->len, chunks);
  
  if (!publishWithRetry(topic_stream, header, 2)) {
    Serial.println("Failed to send frame header");
    esp_camera_fb_return(fb);
    failedPublishes++;
    return;
  }
  
  // Send chunks
  bool success = true;
  for (int i = 0; i < chunks; i++) {
    int offset = i * chunkSize;
    int len = min(chunkSize, (int)(fb->len - offset));
    
    // Try to publish chunk
    if (!mqtt.publish(topic_stream, fb->buf + offset, len, false)) {
      Serial.printf("Failed chunk %d/%d\n", i + 1, chunks);
      success = false;
      failedPublishes++;
      break;
    }
    
    // Small delay and process incoming messages
    delay(10);
    mqtt.loop();
  }
  
  if (success) {
    publishWithRetry(topic_stream, "FRAME_END", 2);
    successfulFrames++;
    
    // Print stats every 20 successful frames
    if (successfulFrames % 20 == 0) {
      Serial.printf("✓ Frames sent: %d (Failed: %d) | Size: %d bytes\n", 
                    successfulFrames, failedPublishes, fb->len);
    }
  }
  
  esp_camera_fb_return(fb);
}

void reconnect() {
  // Don't try to reconnect too frequently
  if (millis() - lastReconnect < 5000) {
    return;
  }
  lastReconnect = millis();
  
  if (!mqtt.connected()) {
    Serial.print("Connecting to MQTT...");
    
    String clientId = "ESP32CAM_" + String(random(0xffff), HEX);
    
    // Try to connect
    if (mqtt.connect(clientId.c_str(), mqtt_user, mqtt_pass, topic_status, 0, true, "ESP32-CAM Offline")) {
      Serial.println("connected!");
      
      // Subscribe to command topic
      mqtt.subscribe(topic_command);
      
      // Publish online status
      mqtt.publish(topic_status, "ESP32-CAM Online", true);
      
      Serial.println("✓ Ready for commands");
    } else {
      Serial.print("failed, rc=");
      Serial.print(mqtt.state());
      Serial.println(" (retrying in 5s)");
    }
  }
}

void setup() {
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);
  
  Serial.begin(115200);
  Serial.println("\n========================================");
  Serial.println("   ESP32-CAM MQTT PlantEye Starting    ");
  Serial.println("========================================");

  pinMode(FLASH_GPIO_NUM, OUTPUT);
  digitalWrite(FLASH_GPIO_NUM, HIGH);

  // Initialize camera
  setup_camera();

  // Connect to WiFi
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\n✗ WiFi failed!");
    ESP.restart();
  }

  Serial.println("\n✓ WiFi connected");
  Serial.print("✓ IP: ");
  Serial.println(WiFi.localIP());

  // Setup MQTT with optimized settings
  mqtt.setServer(mqtt_server, mqtt_port);
  mqtt.setCallback(callback);
  mqtt.setBufferSize(4096);  // 4KB buffer (smaller is more stable)
  mqtt.setKeepAlive(90);     // 90 second keep-alive
  mqtt.setSocketTimeout(20);  // 20 second timeout

  Serial.println("========================================");
  Serial.println("        🌱 MQTT CAMERA READY! 🌱       ");
  Serial.println("========================================");
  Serial.println("Commands:");
  Serial.println("  CAPTURE      - Take a photo");
  Serial.println("  START_STREAM - Start video stream");
  Serial.println("  STOP_STREAM  - Stop video stream");
  Serial.println("  FLASH_ON     - Turn on LED");
  Serial.println("  FLASH_OFF    - Turn off LED");
  Serial.println("========================================\n");
}

void loop() {
  // Reconnect if needed
  if (!mqtt.connected()) {
    streamingActive = false;  // Stop streaming if disconnected
    reconnect();
  }
  
  // Process MQTT messages
  if (mqtt.connected()) {
    mqtt.loop();
    
    // Send stream frames if active
    if (streamingActive) {
      sendStreamFrame();
    }
  }
  
  delay(10);
}