import os
import sys
import time
import random
import traceback
import cv2
import numpy as np
from flask import Flask, Response, jsonify, request

app = Flask(__name__)

# --- Camera backend selection ---
# Raspberry Pi OS (Bullseye+) exposes the CSI Camera Module 2 through the
# libcamera stack, not the legacy V4L2 /dev/video0 device, so
# cv2.VideoCapture(0) cannot see it. Use Picamera2 (libcamera bindings) when
# available; otherwise fall back to a USB webcam via OpenCV for desktop dev.
USE_PICAMERA2 = False
picam2 = None
camera = None

print(">>> Initializing camera backend...", flush=True)
try:
    from picamera2 import Picamera2
    print(">>> picamera2 imported, opening camera...", flush=True)

    picam2 = Picamera2()
    _config = picam2.create_video_configuration(
        main={"size": (1280, 720), "format": "BGR888"}
    )
    picam2.configure(_config)
    picam2.start()
    time.sleep(1)  # let auto-exposure/white-balance settle
    USE_PICAMERA2 = True
    print("Camera backend: Picamera2 (libcamera / CSI Camera Module 2)", flush=True)
except Exception:
    print(">>> Picamera2 init failed with exception:", file=sys.stderr, flush=True)
    traceback.print_exc()
    print("Falling back to OpenCV VideoCapture", flush=True)
    camera = cv2.VideoCapture(0)
    if not camera.isOpened():
        camera = cv2.VideoCapture(1)
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    print("Camera backend: OpenCV VideoCapture (USB webcam)", flush=True)


def read_frame():
    if USE_PICAMERA2:
        try:
            return True, picam2.capture_array()
        except Exception:
            print(">>> Picamera2 capture error:", file=sys.stderr, flush=True)
            traceback.print_exc()
            return False, None
    return camera.read()


# Base directory for all scans (cross-platform: works on both Windows dev
# machine and the Raspberry Pi's Linux filesystem).
SAVE_DIR = os.path.join(os.path.expanduser("~"), "atlas_scans_test")

def generate_frames():
    while True:
        success, frame = read_frame()
        if not success:
            frame = np.zeros((360, 640, 3), dtype=np.uint8)
            cv2.putText(frame, "CAMERA ERROR", (150, 180), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 3)

        display_frame = cv2.resize(frame, (640, 360))
        _, buffer = cv2.imencode('.jpg', display_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/capture', methods=['POST'])
def capture_and_analyze():
    data = request.json
    scan_id = data.get('scan_id', 'UNKNOWN_SCAN')
    side = data.get('side', 'Left')
    view = data.get('view', 'CC')

    success, frame = read_frame()
    if not success:
        return jsonify({'error': 'Failed to capture from hardware sensor'}), 500

    # Nested folder structure -> atlas_scans_test / SCAN-0002 / Left /
    folder_path = os.path.join(SAVE_DIR, scan_id, side)
    os.makedirs(folder_path, exist_ok=True)

    timestamp = int(time.time())
    file_path = os.path.join(folder_path, f"{side}_{view}_{timestamp}.png")
    cv2.imwrite(file_path, frame, [int(cv2.IMWRITE_PNG_COMPRESSION), 0])

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
