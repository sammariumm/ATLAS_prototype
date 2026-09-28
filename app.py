import os
import time
import cv2
import numpy as np
from flask import Flask, Response, jsonify, request

app = Flask(__name__)

camera = cv2.VideoCapture(0)
if not camera.isOpened():
    camera = cv2.VideoCapture(1)

camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

# Base directory for all scans
SAVE_DIR = "C:/atlas_scans_test/"

def generate_frames():
    while True:
        success, frame = camera.read()
        if not success:
            frame = np.zeros((360, 640, 3), dtype=np.uint8)
            cv2.putText(frame, "WEBCAM ERROR", (150, 180), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 3)
            
        display_frame = cv2.resize(frame, (640, 360))
        _, buffer = cv2.imencode('.jpg', display_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

@app.route('/stream')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/capture', methods=['POST'])
def capture_and_analyze():
    data = request.json
    scan_id = data.get('scan_id', 'UNKNOWN_SCAN')
    side = data.get('side', 'Left')
    view = data.get('view', 'CC')

    success, frame = camera.read()
    if not success:
        return jsonify({'error': 'Failed to capture from hardware sensor'}), 500

    # NEW: Create nested folder structure -> atlas_scans_test / SCAN-0002 / Left /
    folder_path = os.path.join(SAVE_DIR, scan_id, side)
    os.makedirs(folder_path, exist_ok=True)

    timestamp = int(time.time())
    file_path = os.path.join(folder_path, f"{side}_{view}_{timestamp}.png")
    cv2.imwrite(file_path, frame, [int(cv2.IMWRITE_PNG_COMPRESSION), 0])

    import random
    time.sleep(2) 
    
    return jsonify({
        'status': 'success',
        'image_path': file_path, # Returns the new deeply nested path to Flutter
        'classification': random.choice(['BI-RADS 1', 'BI-RADS 2', 'BI-RADS 4']),
        'confidence': f"{random.uniform(85.0, 98.0):.1f}%",
        'recommendation': 'Mock bilateral inference completed.'
    })

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, threaded=True)