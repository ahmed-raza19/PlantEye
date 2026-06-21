import cv2
import numpy as np
import paho.mqtt.client as mqtt
from ultralytics import YOLO
import time
import threading
import os
import requests

# ===========================
# CONFIGURATION
# ===========================
MQTT_BROKER = "localhost" 
MQTT_PORT = 1883
MQTT_TOPIC_STREAM = "planteye/camera/stream"
MQTT_TOPIC_COMMAND = "planteye/camera/command"
MQTT_TOPIC_STATUS = "planteye/camera/status"

# Robot Control
ROBOT_IP = "192.168.1.101"  # TODO: set to your motor-controller ESP32's local IP
CMD_FORWARD = f"http://{ROBOT_IP}/forward"
CMD_LEFT    = f"http://{ROBOT_IP}/left"
CMD_RIGHT   = f"http://{ROBOT_IP}/right"
CMD_STOP    = f"http://{ROBOT_IP}/stop"

# Display
DISPLAY_WIDTH = 1280
DISPLAY_HEIGHT = 720

# YOLO
POTTED_PLANT_CLASS = 58 
CONFIDENCE_THRESHOLD = 0.4

# Movement
DEAD_ZONE = 100
STOP_WIDTH = 450

# Capture
OUTPUT_FOLDER = "captured_images"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Frame buffer management
class FrameBuffer:
    def __init__(self):
        self.buffer = bytearray()
        self.receiving = False
        self.expected_size = 0
        self.chunks_received = 0
        self.total_chunks = 0
        self.lock = threading.Lock()
        
    def start_frame(self, size, chunks):
        with self.lock:
            self.buffer = bytearray()
            self.receiving = True
            self.expected_size = size
            self.total_chunks = chunks
            self.chunks_received = 0
            
    def add_chunk(self, data):
        with self.lock:
            if self.receiving:
                self.buffer.extend(data)
                self.chunks_received += 1
                
    def finish_frame(self):
        with self.lock:
            self.receiving = False
            if len(self.buffer) > 0:
                return bytes(self.buffer)
            return None
            
    def reset(self):
        with self.lock:
            self.buffer = bytearray()
            self.receiving = False

# Global variables
frame_buffer = FrameBuffer()
current_frame = None
new_frame_ready = False
frame_lock = threading.Lock()
frames_received = 0
frames_failed = 0
last_frame_time = time.time()
capture_request = False
autopilot = False
last_command = None

def get_next_image_number():
    existing_files = [f for f in os.listdir(OUTPUT_FOLDER) if f.startswith("image") and f.endswith(".jpg")]
    if not existing_files:
        return 1
    numbers = []
    for filename in existing_files:
        try:
            num_str = filename.replace("image", "").replace(".jpg", "")
            numbers.append(int(num_str))
        except ValueError:
            continue
    if numbers:
        return max(numbers) + 1
    return 1

def send_robot_cmd(url, name):
    global last_command
    if name != last_command:
        try:
            requests.get(url, timeout=0.5)
            last_command = name
        except:
            pass

# ===========================
# MQTT CALLBACKS
# ===========================
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"✅ Connected to MQTT Broker at {MQTT_BROKER}:{MQTT_PORT}")
        client.subscribe(MQTT_TOPIC_STREAM)
        client.subscribe(MQTT_TOPIC_STATUS)
        print(f"📡 Subscribed to: {MQTT_TOPIC_STREAM}")
        print(f"📡 Subscribed to: {MQTT_TOPIC_STATUS}")
        
        time.sleep(1)
        print("🚀 Sending START_STREAM command...")
        client.publish(MQTT_TOPIC_COMMAND, "START_STREAM")
    else:
        print(f"❌ Connection failed with code: {rc}")

def on_message(client, userdata, msg):
    global current_frame, new_frame_ready, frames_received, frames_failed, last_frame_time
    
    if msg.topic == MQTT_TOPIC_STATUS:
        try:
            status = msg.payload.decode('utf-8')
            print(f"📢 Status: {status}")
        except:
            pass
        return
    
    payload = msg.payload
    
    try:
        text_message = payload.decode('utf-8')
        
        if text_message.startswith("FRAME:"):
            parts = text_message.split(":")
            if len(parts) == 3:
                size = int(parts[1])
                chunks = int(parts[2])
                frame_buffer.start_frame(size, chunks)
            return
            
        elif text_message == "FRAME_END":
            frame_data = frame_buffer.finish_frame()
            
            if frame_data and len(frame_data) > 0:
                try:
                    np_arr = np.frombuffer(frame_data, dtype=np.uint8)
                    decoded_img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                    
                    if decoded_img is not None:
                        with frame_lock:
                            current_frame = decoded_img
                            new_frame_ready = True
                        frames_received += 1
                        last_frame_time = time.time()
                        
                        if frames_received % 30 == 0:
                            fps = 30 / (time.time() - last_frame_time + 0.001)
                            print(f"📊 Frames: {frames_received} | Failed: {frames_failed} | FPS: {fps:.1f}")
                    else:
                        frames_failed += 1
                except Exception as e:
                    frames_failed += 1
            else:
                frames_failed += 1
                
            frame_buffer.reset()
            return
            
    except UnicodeDecodeError:
        pass
    
    if frame_buffer.receiving:
        frame_buffer.add_chunk(payload)

def on_disconnect(client, userdata, rc):
    if rc != 0:
        print(f"⚠️ Unexpected disconnection. Code: {rc}")

# ===========================
# MAIN APPLICATION
# ===========================
def main():
    global current_frame, new_frame_ready, capture_request, autopilot
    
    print("\n" + "="*70)
    print("  🌱 ESP32-CAM MQTT RECEIVER WITH YOLO DETECTION 🌱")
    print(f"  Display Resolution: {DISPLAY_WIDTH}x{DISPLAY_HEIGHT}")
    print(f"  Capture Folder: {OUTPUT_FOLDER}/")
    print("="*70 + "\n")
    
    print("⏳ Loading YOLO model...")
    try:
        model = YOLO('yolov8n.pt')
        print("✅ YOLO model loaded successfully\n")
    except Exception as e:
        print(f"❌ Failed to load YOLO: {e}")
        return
    
    client = mqtt.Client(client_id="PlantEye_Receiver", clean_session=True)
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect
    
    try:
        print(f"🔌 Connecting to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}...")
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        print("💡 Make sure Mosquitto is running!")
        return
    
    client.loop_start()
    
    print("\n" + "="*70)
    print("  📸 Press 'C' to CAPTURE | 'A' for AUTOPILOT | 'Q' to QUIT")
    print("="*70 + "\n")
    
    capture_count = get_next_image_number() - 1
    frame_count = 0
    no_frame_warning_shown = False
    
    try:
        while True:
            if new_frame_ready and current_frame is not None:
                with frame_lock:
                    frame = current_frame.copy()
                    new_frame_ready = False
                
                frame_count += 1
                no_frame_warning_shown = False
                
                h_orig, w_orig = frame.shape[:2]
                center_x = w_orig // 2
                
                # Run YOLO
                results = model(frame, classes=[POTTED_PLANT_CLASS], 
                              conf=CONFIDENCE_THRESHOLD, verbose=False)
                
                plant_count = 0
                target = None
                max_area = 0
                
                for result in results:
                    for box in result.boxes:
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        conf = float(box.conf[0])
                        
                        plant_count += 1
                        
                        # Draw box
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        
                        # Label
                        label = f"Plant {conf:.2f}"
                        cv2.putText(frame, label, (x1, y1 - 10),
                                  cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                        
                        # Find largest (target)
                        width = x2 - x1
                        area = width * (y2 - y1)
                        if area > max_area:
                            max_area = area
                            cx = (x1 + x2) // 2
                            target = (x1, y1, x2, y2, cx, width)
                
                # Autopilot logic
                action = "SEARCHING"
                if autopilot and target:
                    tx1, ty1, tx2, ty2, tcx, twidth = target
                    
                    # Highlight target
                    cv2.rectangle(frame, (tx1, ty1), (tx2, ty2), (0, 255, 255), 3)
                    cv2.circle(frame, (tcx, (ty1+ty2)//2), 8, (0, 255, 255), -1)
                    
                    # Decision
                    if twidth > STOP_WIDTH:
                        send_robot_cmd(CMD_STOP, "STOP")
                        action = "ARRIVED"
                    elif tcx < (center_x - DEAD_ZONE):
                        send_robot_cmd(CMD_LEFT, "LEFT")
                        action = "LEFT"
                    elif tcx > (center_x + DEAD_ZONE):
                        send_robot_cmd(CMD_RIGHT, "RIGHT")
                        action = "RIGHT"
                    else:
                        send_robot_cmd(CMD_FORWARD, "FORWARD")
                        action = "FORWARD"
                elif autopilot:
                    send_robot_cmd(CMD_STOP, "STOP")
                
                # Capture
                if capture_request:
                    capture_request = False
                    capture_count += 1
                    filename = f"image{capture_count}.jpg"
                    cv2.imwrite(os.path.join(OUTPUT_FOLDER, filename), frame)
                    print(f"📸 Saved {filename}")
                
                # Upscale
                big_frame = cv2.resize(frame, (DISPLAY_WIDTH, DISPLAY_HEIGHT), 
                                     interpolation=cv2.INTER_LINEAR)
                
                h, w = big_frame.shape[:2]
                
                # Overlay
                overlay_height = 80
                overlay = big_frame.copy()
                cv2.rectangle(overlay, (0, 0), (DISPLAY_WIDTH, overlay_height), (0, 0, 0), -1)
                cv2.addWeighted(overlay, 0.6, big_frame, 0.4, 0, big_frame)
                
                # Text
                mode = "AUTOPILOT" if autopilot else "MANUAL"
                cv2.putText(big_frame, f"PLANT EYE - {mode} - {action}", (20, 35), 
                          cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)
                
                status_text = f"Plants: {plant_count} | Frames: {frames_received} | Failed: {frames_failed}"
                cv2.putText(big_frame, status_text, (20, 65),
                          cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
                
                # Bottom
                fps_text = f"Frame: {frame_count} | Captures: {capture_count}"
                cv2.putText(big_frame, fps_text, (10, h-20),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                
                # Instructions
                instructions = "A:Autopilot | C:Capture | Q:Quit"
                cv2.putText(big_frame, instructions, (w-450, 35),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
                
                cv2.imshow("Plant Eye HQ Stream", big_frame)
                
            else:
                if not no_frame_warning_shown and time.time() - last_frame_time > 5:
                    print("⏳ Waiting for frames from ESP32-CAM...")
                    no_frame_warning_shown = True
            
            # Keys
            key = cv2.waitKey(1) & 0xFF
            
            if key == ord('q') or key == ord('Q'):
                print("\n🛑 Stopping stream...")
                client.publish(MQTT_TOPIC_COMMAND, "STOP_STREAM")
                if autopilot:
                    send_robot_cmd(CMD_STOP, "STOP")
                time.sleep(0.5)
                break
                
            elif key == ord('c') or key == ord('C'):
                capture_request = True
                
            elif key == ord('a') or key == ord('A'):
                autopilot = not autopilot
                print(f"🤖 Autopilot: {'ON' if autopilot else 'OFF'}")
                if not autopilot:
                    send_robot_cmd(CMD_STOP, "STOP")
                
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted by user")
    
    finally:
        print("\n🧹 Cleaning up...")
        if autopilot:
            send_robot_cmd(CMD_STOP, "STOP")
        client.loop_stop()
        client.disconnect()
        cv2.destroyAllWindows()
        print(f"✅ Session complete! {capture_count} images saved to '{OUTPUT_FOLDER}/'")

if __name__ == "__main__":
    main()