
import cv2
import numpy as np
import os
import time
import tensorflow as tf
from datetime import datetime

# ═══════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════
IMAGE_FOLDER = "captured_images" 
MODEL_NAME = "plant_disease.tflite"
DISPLAY_TIME_SECONDS = 3

# UI DIMENSIONS
DASHBOARD_WIDTH = 1280
DASHBOARD_HEIGHT = 720
CAM_VIEW_WIDTH = 800 
CAM_VIEW_HEIGHT = 600

# COLORS (BGR Format)
C_BG = (15, 15, 25)      # Dark Navy/Black Background
C_PANEL = (30, 30, 40)   # Side Panel
C_ACCENT = (0, 255, 255) # Cyan/Yellow Accent
C_TEXT = (220, 220, 220)
C_HEALTHY = (0, 255, 50) # Neon Green
C_DISEASE = (50, 50, 255)# Bright Red

# ═══════════════════════════════════════════════════════════
# KNOWLEDGE BASE: TREATMENTS
# ═══════════════════════════════════════════════════════════
TREATMENT_DB = {
    "healthy": "Plant is in good condition. Continue regular watering and monitoring.",
    "scab": "Fungal infection. Prune infected leaves. Apply Fungicide (Captan or Sulfur). Improve air circulation.",
    "rot": "Rot is often caused by excess moisture. Reduce watering immediately. Remove rotting parts. Apply copper-based fungicide.",
    "rust": "Fungal Rust. Remove infected leaves. Avoid overhead watering. Use Sulfur or Copper fungicides.",
    "mildew": "Powdery Mildew. Mix 1 tbsp baking soda + 1 tsp oil in 1 gallon water and spray. Improve sunlight exposure.",
    "spot": "Leaf Spot (Bacterial/Fungal). Remove debris. Use copper fungicides. Avoid splashing water on leaves.",
    "blight": "Serious infection. Remove and destroy infected plants immediately to save others. Apply Mancozeb or Copper.",
    "mite": "Spider Mites. Spray with strong stream of water or use Neem Oil / Insecticidal Soap.",
    "virus": "Viral infection (Mosaic/Curl). No cure. Remove plant to prevent spread. Control aphids/pests.",
    "scorch": "Leaf Scorch. Often due to drought or nutrient burn. Water deeply. Check fertilizer levels.",
    "greening": "Citrus Greening. No cure. Remove tree to prevent spread. Control psyllid insects."
}

def get_treatment(disease_name):
    name_lower = disease_name.lower()
    for key, treatment in TREATMENT_DB.items():
        if key in name_lower:
            return treatment
    return "Consult a local plant pathologist for specific advice."

# 38 Classes
CLASS_NAMES = [
    'Apple___Apple_scab', 'Apple___Black_rot', 'Apple___Cedar_apple_rust', 'Apple___healthy',
    'Blueberry___healthy', 'Cherry_(including_sour)___Powdery_mildew', 'Cherry_(including_sour)___healthy',
    'Corn_(maize)___Cercospora_leaf_spot Gray_leaf_spot', 'Corn_(maize)___Common_rust_', 
    'Corn_(maize)___Northern_Leaf_Blight', 'Corn_(maize)___healthy', 'Grape___Black_rot', 
    'Grape___Esca_(Black_Measles)', 'Grape___Leaf_blight_(Isariopsis_Leaf_Spot)', 'Grape___healthy',
    'Orange___Haunglongbing_(Citrus_greening)', 'Peach___Bacterial_spot', 'Peach___healthy',
    'Pepper,_bell___Bacterial_spot', 'Pepper,_bell___healthy', 'Potato___Early_blight', 
    'Potato___Late_blight', 'Potato___healthy', 'Raspberry___healthy', 'Soybean___healthy', 
    'Squash___Powdery_mildew', 'Strawberry___Leaf_scorch', 'Strawberry___healthy', 
    'Tomato___Bacterial_spot', 'Tomato___Early_blight', 'Tomato___Late_blight', 'Tomato___Leaf_Mold', 
    'Tomato___Septoria_leaf_spot', 'Tomato___Spider_mites Two-spotted_spider_mite', 'Tomato___Target_Spot', 
    'Tomato___Tomato_Yellow_Leaf_Curl_Virus', 'Tomato___Tomato_mosaic_virus', 'Tomato___healthy'
]

# ═══════════════════════════════════════════════════════════
# LOAD MODEL
# ═══════════════════════════════════════════════════════════
print("🔄 Loading AI Model...")
try:
    interpreter = tf.lite.Interpreter(model_path=MODEL_NAME)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()
    print("✅ Model Loaded!")
except Exception as e:
    exit(f"❌ Error: {e}")

# ═══════════════════════════════════════════════════════════
# UI DRAWING
# ═══════════════════════════════════════════════════════════
def draw_text_wrapped(img, text, x, y, font, scale, color, thickness, max_width):
    words = text.split(' ')
    line = ''
    dy = int(30 * scale)
    for word in words:
        test_line = line + word + ' '
        (w, h), _ = cv2.getTextSize(test_line, font, scale, thickness)
        if w > max_width:
            cv2.putText(img, line, (x, y), font, scale, color, thickness)
            line = word + ' '
            y += dy
        else:
            line = test_line
    cv2.putText(img, line, (x, y), font, scale, color, thickness)

def create_dashboard(frame, top_predictions, crop_coords):
    # 1. Base Canvas
    dashboard = np.zeros((DASHBOARD_HEIGHT, DASHBOARD_WIDTH, 3), dtype=np.uint8)
    dashboard[:] = C_BG 

    # 2. Camera View (Resized)
    cam_view = cv2.resize(frame, (CAM_VIEW_WIDTH, CAM_VIEW_HEIGHT))
    
    # Draw Sniper Scope on Cam View
    h_orig, w_orig = frame.shape[:2]
    scale_x = CAM_VIEW_WIDTH / w_orig
    scale_y = CAM_VIEW_HEIGHT / h_orig
    x1, y1, x2, y2 = crop_coords
    dx1, dy1 = int(x1 * scale_x), int(y1 * scale_y)
    dx2, dy2 = int(x2 * scale_x), int(y2 * scale_y)
    
    # Overlay Box
    mask = np.zeros_like(cam_view)
    cv2.rectangle(mask, (dx1, dy1), (dx2, dy2), (255, 255, 255), -1)
    darkened = cv2.addWeighted(cam_view, 0.3, np.zeros_like(cam_view), 0.7, 0)
    cam_view = np.where(mask == (255, 255, 255), cam_view, darkened)
    cv2.rectangle(cam_view, (dx1, dy1), (dx2, dy2), C_ACCENT, 1)

    # Place Camera in Dashboard
    margin = 20
    dashboard[margin:margin+CAM_VIEW_HEIGHT, margin:margin+CAM_VIEW_WIDTH] = cam_view
    cv2.rectangle(dashboard, (margin, margin), (margin+CAM_VIEW_WIDTH, margin+CAM_VIEW_HEIGHT), C_PANEL, 4)

    # ---------------- RIGHT PANEL (DATA) ----------------
    panel_x = margin + CAM_VIEW_WIDTH + margin
    panel_width = DASHBOARD_WIDTH - panel_x - margin
    
    # Header
    cv2.putText(dashboard, "DIAGNOSTIC UNIT", (panel_x, 50), cv2.FONT_HERSHEY_DUPLEX, 0.8, C_TEXT, 2)
    current_time = datetime.now().strftime("%H:%M:%S")
    cv2.putText(dashboard, f"TIME: {current_time}", (panel_x, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (150, 150, 150), 1)
    
    cv2.line(dashboard, (panel_x, 90), (DASHBOARD_WIDTH - margin, 90), C_PANEL, 2)

    # --- TOP STATUS ---
    best_name, best_score = top_predictions[0]
    clean_name = best_name.split("___")[-1].replace("_", " ")
    is_healthy = "healthy" in best_name.lower()
    status_color = C_HEALTHY if is_healthy else C_DISEASE
    status_text = "HEALTHY" if is_healthy else "INFECTED"

    cv2.rectangle(dashboard, (panel_x, 100), (DASHBOARD_WIDTH - margin, 160), status_color, -1)
    cv2.putText(dashboard, status_text, (panel_x + 10, 145), cv2.FONT_HERSHEY_DUPLEX, 1.2, (0,0,0), 2)

    # --- LEADERBOARD (Top 4) ---
    cv2.putText(dashboard, "CONFIDENCE ANALYSIS:", (panel_x, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.5, C_ACCENT, 1)
    
    y_offset = 230
    for i in range(min(4, len(top_predictions))):
        name, score = top_predictions[i]
        c_name = name.split("___")[-1].replace("_", " ")
        
        # Calculate color based on 'healthy' status
        bar_color = C_HEALTHY if "healthy" in c_name.lower() else C_DISEASE
        if i == 0: bar_color = status_color # Match main status for top result

        # Text
        cv2.putText(dashboard, f"{c_name}", (panel_x, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.5, C_TEXT, 1)
        
        # Percentage Text (Right aligned)
        score_text = f"{score:.1%}"
        (tw, th), _ = cv2.getTextSize(score_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.putText(dashboard, score_text, (DASHBOARD_WIDTH - margin - tw, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.5, C_TEXT, 1)
        
        # Progress Bar
        bar_max_width = panel_width
        bar_w = int(score * bar_max_width)
        cv2.rectangle(dashboard, (panel_x, y_offset + 5), (panel_x + bar_max_width, y_offset + 12), (50, 50, 60), -1) # BG
        cv2.rectangle(dashboard, (panel_x, y_offset + 5), (panel_x + bar_w, y_offset + 12), bar_color, -1) # Fill

        y_offset += 45

    # --- TREATMENT SECTION ---
    cv2.line(dashboard, (panel_x, 410), (DASHBOARD_WIDTH - margin, 410), C_PANEL, 2)
    cv2.putText(dashboard, "RECOMMENDED ACTION:", (panel_x, 440), cv2.FONT_HERSHEY_SIMPLEX, 0.5, C_ACCENT, 1)
    
    treatment_text = get_treatment(clean_name)
    
    # Dark box for text
    cv2.rectangle(dashboard, (panel_x, 450), (DASHBOARD_WIDTH - margin, 650), (25, 25, 35), -1)
    cv2.rectangle(dashboard, (panel_x, 450), (DASHBOARD_WIDTH - margin, 650), C_PANEL, 1)
    
    # Draw text
    draw_text_wrapped(dashboard, treatment_text, panel_x + 10, 480, cv2.FONT_HERSHEY_SIMPLEX, 0.55, C_TEXT, 1, panel_width - 20)

    return dashboard

# ═══════════════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════════════
current_image_num = 1
waiting_printed = False

cv2.namedWindow("Plant Doctor Pro", cv2.WINDOW_NORMAL)
cv2.resizeWindow("Plant Doctor Pro", DASHBOARD_WIDTH, DASHBOARD_HEIGHT)

print(f"\n📂 Watching folder '{IMAGE_FOLDER}'...")

while True:
    filename = f"image{current_image_num}.jpg" 
    file_path = os.path.join(IMAGE_FOLDER, filename)

    if os.path.exists(file_path):
        waiting_printed = False 
        print(f"\n📸 Processing {filename}...")
        
        try:
            frame = cv2.imread(file_path)
            if frame is None: raise ValueError("Empty image")
        except:
            time.sleep(0.5)
            continue

        h, w = frame.shape[:2]

        # STEP 1: SNIPER CROP (Center 60%)
        box_size_ratio = 0.6 
        center_x, center_y = w // 2, h // 2
        half_w, half_h = int((w * box_size_ratio) / 2), int((h * box_size_ratio) / 2)
        x1, y1 = max(0, center_x - half_w), max(0, center_y - half_h)
        x2, y2 = min(w, center_x + half_w), min(h, center_y + half_h)
        crop_coords = (x1, y1, x2, y2)
        
        # STEP 2: DIAGNOSE
        img_to_diagnose = frame[y1:y2, x1:x2]
        img_resized = cv2.resize(img_to_diagnose, (224, 224))
        input_data = np.array(img_resized, dtype=np.float32) / 255.0
        input_data = np.expand_dims(input_data, axis=0)

        interpreter.set_tensor(input_details[0]['index'], input_data)
        interpreter.invoke()
        output_data = interpreter.get_tensor(output_details[0]['index'])[0]

        top_indices = np.argsort(output_data)[-5:][::-1]
        top_predictions = []
        for idx in top_indices:
            top_predictions.append((CLASS_NAMES[idx], output_data[idx]))

        # STEP 3: FANCY DASHBOARD
        final_screen = create_dashboard(frame, top_predictions, crop_coords)
        
        cv2.imshow("Plant Doctor Pro", final_screen)
        cv2.waitKey(1)
        
        print(f"✅ Diagnosis: {top_predictions[0][0]}")
        
        time.sleep(DISPLAY_TIME_SECONDS)
        current_image_num += 1

    else:
        if not waiting_printed:
            print(f"⏳ Waiting for {filename}...", end="\r")
            waiting_printed = True
        
        if cv2.waitKey(100) & 0xFF == ord('q'): break

cv2.destroyAllWindows()