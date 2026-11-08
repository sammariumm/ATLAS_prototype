import glob
import os
import re
import stat
import sys
import textwrap
import time
import threading
import traceback
from urllib.parse import urlsplit, urlunsplit

import cv2
import numpy as np
from flask import Flask, Response, jsonify, request

import atlas_convert
import atlas_models
import atlas_preprocess

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Settings (environment variables; the defaults suit the Raspberry Pi set-up)
# ---------------------------------------------------------------------------
def _env_int(name, default):
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_float(name, default):
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_flag(name, default):
    v = os.environ.get(name, "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return default


def _parse_size(text, default):
    try:
        w, h = text.lower().replace(",", "x").split("x")
        return int(w), int(h)
    except ValueError:
        return default


# ATLAS_CAMERA=none -> do not open any camera (softcopy-only machine, tests)
CAMERA_MODE = os.environ.get("ATLAS_CAMERA", "auto").strip().lower()
# USB webcam (a PC, or a Pi without the CSI camera): "" = use the first /dev/video* that gives a picture,
# or a number (0, 1, ...) or a device path (/dev/video2) to force one.
CAMERA_INDEX = os.environ.get("ATLAS_CAMERA_INDEX", "").strip()
# A network camera (a phone running a camera app, an IP camera): the address of its video stream, for example
# http://192.168.43.1:8080/video .  When set, the Raspberry Pi camera and USB webcams are not used at all.
CAMERA_URL = os.environ.get("ATLAS_CAMERA_URL", "").strip()

# Camera size.  1640x1232 is the Camera Module 2's full-field-of-view 2x2-binned mode (4:3).  The old 1280x720
# is a cropped 16:9 mode, which loses field of view and resolution for a portrait film.
CAMERA_SIZE = _parse_size(os.environ.get("ATLAS_CAMERA_SIZE", ""), (1640, 1232))

# The picture is rotated this many degrees COUNTER-CLOCKWISE before anything else sees it (preview, saved
# photo, film processing).  0, 90, 180 or 270.  If the film comes out upside down or sideways, change this.
CAMERA_ROTATION = _env_int("ATLAS_CAMERA_ROTATION", 90)
if CAMERA_ROTATION not in (0, 90, 180, 270):
    print(">>> ATLAS_CAMERA_ROTATION must be 0, 90, 180 or 270; using 90", flush=True)
    CAMERA_ROTATION = 90

# Auto-exposure is turned OFF.  Leave these at 0 to freeze whatever auto-exposure settled on at start-up
# (start the backend with the lightbox on), or set them to fixed values.
EXPOSURE_US = _env_int("ATLAS_EXPOSURE_US", 0)         # exposure time in microseconds
ANALOGUE_GAIN = _env_float("ATLAS_ANALOGUE_GAIN", 0.0)  # sensor gain, 1.0 = lowest noise
LOCK_AWB = _env_flag("ATLAS_LOCK_AWB", False)           # also freeze the white balance

CAPTURE_AVG = max(1, _env_int("ATLAS_CAPTURE_AVG", 4))  # frames averaged per still (less sensor noise)
SAVE_DEBUG = _env_flag("ATLAS_SAVE_DEBUG", True)         # save debug pictures of the film processing
REQUIRE_TISSUE = _env_flag("ATLAS_REQUIRE_TISSUE", True)  # reject camera shots in which no breast is found

# Base directory for all scans (cross-platform: works on both Windows dev machine and the Raspberry Pi).
SAVE_DIR = os.environ.get("ATLAS_SCAN_DIR") or os.path.join(os.path.expanduser("~"), "atlas_scans_test")
# Softcopy files (DICOM / PNG / ...) are picked from a USB stick that is plugged into the device (the kiosk has no
# keyboard or file manager, so nobody can copy files into a folder), and from this inbox folder, for anything that
# does put files there (serial transfer, scp, ...).
INBOX_DIR = os.environ.get("ATLAS_INBOX_DIR") or os.path.join(os.path.expanduser("~"), "atlas_inbox")
try:
    os.makedirs(INBOX_DIR, exist_ok=True)
except OSError:
    pass
# A USB stick counts when it is mounted below one of these folders (Raspberry Pi OS: /media/<user>/<label>;
# Arch / most desktops: /run/media/<user>/<label>).  Separate several folders with ":".
MEDIA_ROOTS = [r for r in os.environ.get("ATLAS_MEDIA_ROOTS", "/media:/run/media").split(os.pathsep) if r.strip()]


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------
# Raspberry Pi OS (Bullseye+) exposes the CSI Camera Module 2 through the
# libcamera stack, not the legacy V4L2 /dev/video0 device, so
# cv2.VideoCapture(0) cannot see it. Use Picamera2 (libcamera bindings) when
# available; otherwise fall back to a USB webcam via OpenCV for desktop dev.
USE_PICAMERA2 = False
CAMERA_BACKEND = "none"
picam2 = None
camera = None
EXPOSURE_STATE = {}
_camera_lock = threading.Lock()  # cv2.VideoCapture is not thread-safe


PICAM_NO_PICTURE = ("The Raspberry Pi camera is connected but sends no picture. Check that the ribbon cable is "
                    "pushed in all the way at both ends (camera port, not DISPLAY), or try another cable.")
_picam_call_lock = threading.Lock()
_picam_stuck = None            # the worker of a Picamera2 call that timed out and has not returned yet


def _picam_timeout():
    """Seconds to wait for one picture from the Pi camera (a long exposure needs longer)."""
    return max(5.0, 3.0 * max(EXPOSURE_US, 0) / 1e6 + 2.0)


def _picam_call(fn, timeout=None):
    """Runs a Picamera2 call that waits for the sensor (capture_array, capture_metadata) and raises TimeoutError if
    no picture comes.  Without this a camera whose ribbon cable is loose blocks the call for ever and, at start-up,
    the whole backend with it.  While a timed-out call is still waiting, further calls fail at once (so a stream does
    not pile up threads); as soon as that call returns, because pictures flow again, the camera works again."""
    global _picam_stuck
    timeout = _picam_timeout() if timeout is None else timeout
    with _picam_call_lock:
        if _picam_stuck is not None:
            if _picam_stuck.is_alive():
                raise TimeoutError("the camera has not delivered a picture yet")
            _picam_stuck = None
        box = {}

        def work():
            try:
                box["result"] = fn()
            except BaseException as exc:            # handed to the caller below
                box["error"] = exc

        worker = threading.Thread(target=work, name="atlas-picamera-call", daemon=True)
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            _picam_stuck = worker
            raise TimeoutError("no picture from the camera within %.0f s" % timeout)
    if "error" in box:
        raise box["error"]
    return box["result"]


def _lock_picamera_exposure():
    """Turn libcamera's auto-exposure OFF and pin exposure time + gain, so every film is photographed the same way."""
    global EXPOSURE_STATE
    try:
        if EXPOSURE_US <= 0 or ANALOGUE_GAIN <= 0:
            time.sleep(1.0)  # let auto-exposure settle once on the scene, then freeze what it chose
        md = _picam_call(picam2.capture_metadata)
        exposure = EXPOSURE_US if EXPOSURE_US > 0 else int(md.get("ExposureTime", 10000))
        gain = ANALOGUE_GAIN if ANALOGUE_GAIN > 0 else float(md.get("AnalogueGain", 1.0))
        controls = {"AeEnable": False, "ExposureTime": exposure, "AnalogueGain": gain}
        if exposure + 1000 > 33333:  # long exposures need a longer frame time
            controls["FrameDurationLimits"] = (exposure + 1000, exposure + 1000)
        if LOCK_AWB:
            controls["AwbEnable"] = False
            gains = md.get("ColourGains")
            if gains:
                controls["ColourGains"] = (float(gains[0]), float(gains[1]))
        picam2.set_controls(controls)
        time.sleep(0.5)  # a few frames for the sensor to take the new values
        md = _picam_call(picam2.capture_metadata)
        EXPOSURE_STATE = {"auto_exposure": False,
                          "exposure_us": md.get("ExposureTime"), "analogue_gain": md.get("AnalogueGain"),
                          "awb_locked": LOCK_AWB}
        print(">>> Auto-exposure OFF: ExposureTime=%s us, AnalogueGain=%s (requested %s us, gain %.2f)"
              % (md.get("ExposureTime"), md.get("AnalogueGain"), exposure, gain), flush=True)
    except Exception:
        print(">>> Could not turn auto-exposure off:", file=sys.stderr, flush=True)
        traceback.print_exc()


def _lock_opencv_exposure():
    """Best effort for a USB webcam (desktop development): webcams and drivers differ a lot."""
    global EXPOSURE_STATE
    try:
        manual = 0.25 if sys.platform.startswith("win") else 1  # 'manual' has a different code per backend
        camera.set(cv2.CAP_PROP_AUTO_EXPOSURE, manual)
        raw = os.environ.get("ATLAS_OPENCV_EXPOSURE", "").strip()
        if raw:
            camera.set(cv2.CAP_PROP_EXPOSURE, float(raw))
        EXPOSURE_STATE = {"auto_exposure": "requested off (webcam: not guaranteed)",
                          "exposure": camera.get(cv2.CAP_PROP_EXPOSURE)}
        print(">>> Webcam auto-exposure requested OFF (not every webcam/driver supports this); "
              "set the exposure with ATLAS_OPENCV_EXPOSURE", flush=True)
    except Exception:
        print(">>> Could not change the webcam exposure mode:", file=sys.stderr, flush=True)
        traceback.print_exc()


# What the camera is doing, shown by /health and written onto the stream picture when there is no picture.
# state: "starting" | "ok" | "off" (ATLAS_CAMERA=none) | "not_found" | "read_failed"
CAMERA_STATUS = {"state": "starting", "detail": ""}
_camera_ok_detail = ""


def _set_camera_status(state, detail):
    CAMERA_STATUS["state"], CAMERA_STATUS["detail"] = state, detail


WEBCAM_PROBE_TIMEOUT = 6.0     # seconds a webcam may take to deliver its first picture before it is given up
NETWORK_PROBE_TIMEOUT = 15.0   # the same for a network camera at start-up (Wi-Fi, name lookup, app start)
NETWORK_RETRY_TIMEOUT = 4.0    # ... and for each try to get a dropped network stream back
NETWORK_RETRY_EVERY = 5.0      # seconds between those tries


def _is_stream_url(source):
    return isinstance(source, str) and re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", source) is not None


def _public_url(url):
    """The address without user name, password or query: those must not end up in the log, /health or the picture."""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if ":" in host:
            host = "[" + host + "]"
        netloc = host + (":%d" % parts.port if parts.port else "")
        return urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    except ValueError:
        return "<invalid address>"


def _open_stream(url):
    """cv2.VideoCapture for a network stream, with time limits so that a dead stream cannot block a read for ever."""
    try:
        return cv2.VideoCapture(url, cv2.CAP_FFMPEG,
                                [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 8000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 8000])
    except (TypeError, AttributeError, cv2.error):       # an OpenCV without the parameter list
        return cv2.VideoCapture(url, cv2.CAP_FFMPEG)


def _linux_usb_webcams():
    """The /dev/videoN capture nodes that belong to a USB camera (UVC).

    Only those: a Raspberry Pi has dozens of V4L2 nodes of its own (video codec, ISP, CSI receiver, ...) that are not
    cameras, and reading from them can block for minutes.  A UVC camera has two nodes, the second one carries
    metadata only (its sysfs `index` is not 0)."""
    nodes = []
    for node in glob.glob("/sys/class/video4linux/video[0-9]*"):
        try:
            with open(node + "/index") as fh:
                if int(fh.read().strip() or 0) != 0:
                    continue
        except (OSError, ValueError):
            pass
        if re.search(r"/usb\d+/", os.path.realpath(node)):
            nodes.append("/dev/" + os.path.basename(node))
    return sorted(nodes, key=lambda path: int(re.sub(r"\D", "", path) or 0))


def _webcam_candidates():
    """The webcams to try: the forced one, else every USB camera (Linux) or the indices 0 to 2."""
    if CAMERA_INDEX:
        return [int(CAMERA_INDEX) if CAMERA_INDEX.isdigit() else CAMERA_INDEX]
    if sys.platform.startswith("linux"):
        return _linux_usb_webcams()
    return [0, 1, 2]


def _probe_webcam(source, backend, timeout=None):
    """(VideoCapture or None, problem).  Opens `source` (a device or a stream address) and reads a picture; never takes
    longer than the time limit (a stuck driver or a dead stream is abandoned, not waited for)."""
    network = _is_stream_url(source)
    label = _public_url(source) if network else source
    if timeout is None:
        timeout = NETWORK_PROBE_TIMEOUT if network else WEBCAM_PROBE_TIMEOUT
    box = {}

    def work():
        cap = _open_stream(source) if network else cv2.VideoCapture(source, backend)
        box["cap"] = cap
        if not cap.isOpened():
            box["problem"] = (f"{label} cannot be opened" if network else
                              f"{label} cannot be opened (in use by another program, or no permission: "
                              f"is your user in the 'video' group?)")
            return
        for _ in range(8):
            ok, frame = cap.read()
            if ok and frame is not None and frame.size:
                box["ok"] = True
                return
        box["problem"] = f"{label} opens but delivers no picture"

    worker = threading.Thread(target=work, name="atlas-webcam-probe", daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        return None, (f"{label} does not answer within {timeout:.0f} s" if network else
                      f"{label} does not answer (stuck driver, or in use by another program)")
    cap = box.get("cap")
    if box.get("ok"):
        return cap, None
    if cap is not None:
        cap.release()
    return None, box.get("problem", f"{label} gave no picture")


def _open_webcam(url=None, timeout=None):
    """Opens a camera that really delivers a picture.  Returns (VideoCapture or None, text).

    With `url`: that network stream.  Otherwise the first USB webcam that works.  A /dev/video node can exist and
    even open and still never deliver a frame, so a camera only counts when a frame was read from it."""
    if url:
        cap, problem = _probe_webcam(url, cv2.CAP_FFMPEG, timeout)
        if cap is None:
            return None, ("Network camera " + problem + ". Check that the camera app on the phone is running and "
                          "streaming, that the phone and the Pi are on the same network (for example the Pi "
                          "connected to the phone's hotspot) and that the address is right.")
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        return cap, f"Network camera {_public_url(url)}, {w}x{h}"
    candidates = _webcam_candidates()
    if not candidates:
        return None, ("No USB camera found (on Linux `ls /dev/video*` and `v4l2-ctl --list-devices` show what the "
                      "system sees; ATLAS_CAMERA_INDEX=<number or /dev/videoN> forces a device).")
    backend = cv2.CAP_V4L2 if sys.platform.startswith("linux") else cv2.CAP_ANY
    problems = []
    for source in candidates:
        cap, problem = _probe_webcam(source, backend)
        if cap is None:
            problems.append(problem)
            continue
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_SIZE[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_SIZE[1])
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        return cap, f"USB webcam {source}, {w}x{h}"
    return None, "Tried: " + "; ".join(problems) + "."


_stream_retry_at = 0.0


def _reconnect_stream():
    """Network camera only: (re)open the stream when it dropped (Wi-Fi hiccup, phone screen locked) or was not there
    yet (the Pi started before the phone's hotspot).  Tries at most every few seconds.  The caller holds
    _camera_lock, because this swaps `camera`.  Returns True when the stream is open again."""
    global camera, CAMERA_BACKEND, _camera_ok_detail, EXPOSURE_STATE, _stream_retry_at
    if not CAMERA_URL or time.monotonic() < _stream_retry_at:
        return False
    cap, text = _open_webcam(CAMERA_URL, NETWORK_RETRY_TIMEOUT)
    _stream_retry_at = time.monotonic() + NETWORK_RETRY_EVERY
    if cap is None:
        return False
    old, camera = camera, cap
    if old is not None:
        try:
            old.release()
        except Exception:
            pass
    CAMERA_BACKEND, _camera_ok_detail = "opencv", text
    EXPOSURE_STATE = {"auto_exposure": "set in the camera app on the phone"}
    _set_camera_status("ok", text)
    print(">>> Network camera connected: " + text, flush=True)
    return True


def _init_webcam(picamera_problem=None, url=None):
    global camera, CAMERA_BACKEND, _camera_ok_detail, EXPOSURE_STATE, _stream_retry_at
    cap, text = _open_webcam(url)
    if url:
        _stream_retry_at = time.monotonic() + NETWORK_RETRY_EVERY
    if cap is None:
        message = text
        if picamera_problem:
            message = f"The Raspberry Pi camera could not be opened ({picamera_problem}). " + text
        _set_camera_status("not_found", "No camera found. " + message)
        print(">>> No camera found. " + message, flush=True)
        return
    camera, CAMERA_BACKEND, _camera_ok_detail = cap, "opencv", text
    _set_camera_status("ok", text)
    if url:
        EXPOSURE_STATE = {"auto_exposure": "set in the camera app on the phone"}
    else:
        _lock_opencv_exposure()
    print("Camera backend: OpenCV VideoCapture (" + text + ")", flush=True)


def _init_camera():
    global USE_PICAMERA2, CAMERA_BACKEND, picam2, _camera_ok_detail
    if CAMERA_MODE == "none":
        _set_camera_status("off", "The camera is switched off (ATLAS_CAMERA=none: softcopy only). "
                                  "Start the backend without that setting to use a camera.")
        print(">>> ATLAS_CAMERA=none: no camera opened (softcopy only).", flush=True)
        return
    if CAMERA_URL:
        print(">>> ATLAS_CAMERA_URL is set: using the network camera %s (the Raspberry Pi camera and USB webcams "
              "are not used)." % _public_url(CAMERA_URL), flush=True)
        _init_webcam(url=CAMERA_URL)
        return
    print(">>> Initializing camera backend...", flush=True)
    try:
        from picamera2 import Picamera2
        print(">>> picamera2 imported, opening camera...", flush=True)

        picam2 = Picamera2()
        # Picamera2's format naming is inverted from what OpenCV expects: its
        # "RGB888" is actually B,G,R in memory and "BGR888" is actually R,G,B.
        # OpenCV (cv2.imencode/imwrite) wants BGR order, so request "RGB888" here
        # -- using "BGR888" produces a red/blue-swapped, negative-looking image.
        _config = picam2.create_video_configuration(
            main={"size": CAMERA_SIZE, "format": "RGB888"}
        )
        picam2.configure(_config)
        picam2.start()
        USE_PICAMERA2 = True
        CAMERA_BACKEND = "picamera2"
        _camera_ok_detail = "Raspberry Pi camera (Picamera2), %dx%d" % tuple(CAMERA_SIZE)
        try:
            _picam_call(picam2.capture_metadata)          # wait for the first picture
        except TimeoutError:
            _set_camera_status("read_failed", PICAM_NO_PICTURE)
            print(">>> The Raspberry Pi camera opened but sends no picture (libcamera: 'Camera frontend has timed "
                  "out'). " + PICAM_NO_PICTURE + " The backend starts anyway; the live view shows this text. "
                  "`rpicam-hello` shows the same fault if it is the hardware.", flush=True)
            return
        _set_camera_status("ok", _camera_ok_detail)
        _lock_picamera_exposure()
        print("Camera backend: Picamera2 (libcamera / CSI Camera Module 2), size %s, rotation %d deg CCW"
              % (CAMERA_SIZE, CAMERA_ROTATION), flush=True)
    except ImportError as exc:
        print(">>> Picamera2 is not available here (%s): looking for a USB webcam (normal on a PC)." % exc,
              flush=True)
        _init_webcam()
    except Exception as exc:
        print(">>> Picamera2 init failed with exception:", file=sys.stderr, flush=True)
        traceback.print_exc()
        problem = str(exc) or type(exc).__name__
        chain = " ".join(str(e) for e in (exc, exc.__cause__) if e).lower()
        if "busy" in chain or "in use" in chain or "acquire" in chain:
            problem = ("the camera is in use by another program. If the backend is already running (it starts at "
                       "boot as atlas-backend.service) it owns the camera: stop it with "
                       "`sudo systemctl stop atlas-backend.service`, or use that one")
            print(">>> The Raspberry Pi camera is busy: another process owns it (see the message above).",
                  flush=True)
        print("Looking for a USB webcam instead", flush=True)
        _init_webcam(picamera_problem=problem)


_ROTATE_CODES = {
    90: cv2.ROTATE_90_COUNTERCLOCKWISE,
    180: cv2.ROTATE_180,
    270: cv2.ROTATE_90_CLOCKWISE,
}


def rotate_frame(frame):
    code = _ROTATE_CODES.get(CAMERA_ROTATION)
    return frame if code is None else cv2.rotate(frame, code)


def read_frame():
    """(ok, BGR frame) -- already rotated by ATLAS_CAMERA_ROTATION."""
    if USE_PICAMERA2:
        try:
            frame = _picam_call(picam2.capture_array)
        except TimeoutError:
            _set_camera_status("read_failed", PICAM_NO_PICTURE)
            return False, None
        except Exception:
            print(">>> Picamera2 capture error:", file=sys.stderr, flush=True)
            traceback.print_exc()
            _set_camera_status("read_failed", "The camera was opened but gives no picture "
                                              "(cable, power, or another program is using it).")
            return False, None
    elif camera is not None or CAMERA_URL:
        with _camera_lock:
            ok, frame = camera.read() if camera is not None else (False, None)
            if not ok and CAMERA_URL and _reconnect_stream():
                ok, frame = camera.read()
        if not ok:
            if camera is not None:               # (a network camera that never connected keeps its own explanation)
                _set_camera_status("read_failed", "The camera was opened but gives no picture "
                                                  "(unplugged, or another program is using it).")
            return False, None
    else:
        return False, None
    if CAMERA_STATUS["state"] != "ok":
        _set_camera_status("ok", _camera_ok_detail)
    return True, rotate_frame(frame)


def grab_still(n=None):
    """A still for the film processing: the mean of a few consecutive frames (less sensor noise)."""
    n = max(1, CAPTURE_AVG if n is None else n)
    acc, got = None, 0
    for _ in range(n):
        ok, frame = read_frame()
        if not ok or frame is None:
            continue
        acc = frame.astype(np.float32) if acc is None else acc + frame
        got += 1
    if got == 0:
        return None
    return np.clip(np.rint(acc / got), 0, 255).astype(np.uint8)


PREVIEW_MAX_SIDE = 640


def _no_picture_frame():
    """What the live view shows when there is no camera picture: the reason, in words."""
    frame = np.zeros((640, 480, 3), dtype=np.uint8)
    title = {"off": "CAMERA OFF", "not_found": "NO CAMERA FOUND"}.get(CAMERA_STATUS["state"], "CAMERA ERROR")
    cv2.putText(frame, title, (30, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
    y = 130
    for line in textwrap.wrap(CAMERA_STATUS["detail"] or "No picture from the camera.", 36)[:16]:
        cv2.putText(frame, line, (30, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        y += 26
    return frame


def generate_frames():
    while True:
        success, frame = read_frame()
        if not success or frame is None:
            frame = _no_picture_frame()
            time.sleep(0.2)

        # keep the aspect ratio: the picture is portrait after the rotation
        h, w = frame.shape[:2]
        s = PREVIEW_MAX_SIDE / float(max(h, w))
        display_frame = frame
        if s < 1.0:
            display_frame = cv2.resize(frame, (max(1, int(round(w * s))), max(1, int(round(h * s)))),
                                       interpolation=cv2.INTER_AREA)
        _, buffer = cv2.imencode('.jpg', display_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _clean_scan_id(value):
    value = str(value if value else "UNKNOWN_SCAN")
    if not _ID_RE.match(value):
        raise ValueError("Invalid scan id.")
    return value


def _clean_side(value):
    value = str(value or "").strip().capitalize()
    if value not in ("Left", "Right"):
        raise ValueError("side must be 'Left' or 'Right'.")
    return value


def _clean_view(value):
    value = str(value or "").strip().upper()
    if value not in ("CC", "MLO"):
        raise ValueError("view must be 'CC' or 'MLO'.")
    return value


def _inside(base, path):
    """Real path of ``path`` (absolute, or relative to ``base``) -- only if it lies inside ``base``."""
    base_real = os.path.realpath(base)
    candidate = path if os.path.isabs(path) else os.path.join(base_real, path)
    real = os.path.realpath(candidate)
    if os.path.commonpath([base_real, real]) != base_real:
        raise ValueError("That file is outside the allowed folder.")
    return real


def _write_preview(png_path):
    """JPEG preview next to the PNG (the UI and the PDF use it).  Returns (preview path, width, height)."""
    preview = os.path.splitext(png_path)[0] + "_preview.jpg"
    w, h = atlas_preprocess.make_preview(png_path, preview)
    return preview, w, h


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/health')
def health():
    return jsonify({
        'camera': CAMERA_BACKEND,
        'camera_status': dict(CAMERA_STATUS),
        'camera_size': list(CAMERA_SIZE),
        'rotation_ccw_deg': CAMERA_ROTATION,
        'exposure': EXPOSURE_STATE,
        'models': 'mock' if MODELS_ARE_MOCK else 'real',
        'ai': None if MODELS_ARE_MOCK else atlas_models.get_ensemble().info(),
        'scan_dir': SAVE_DIR,
        'inbox_dir': INBOX_DIR,
        'usb_volumes': [v['name'] for v in _usb_volumes()],
    })


@app.route('/capture', methods=['POST'])
def capture():
    """Camera source: photograph the film on the lightbox, turn the photo into a digital-like image."""
    data = request.get_json(silent=True) or {}
    try:
        scan_id = _clean_scan_id(data.get('scan_id'))
        side = _clean_side(data.get('side', 'Left'))
        view = _clean_view(data.get('view', 'CC'))
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    frame = grab_still()
    if frame is None:
        return jsonify({'error': 'Failed to capture from hardware sensor'}), 500

    # Nested folder structure -> atlas_scans_test / SCAN-0002 / Left /
    folder = os.path.join(SAVE_DIR, scan_id, side)
    os.makedirs(folder, exist_ok=True)
    stem = f"{side}_{view}_{int(time.time())}"

    raw_path = os.path.join(folder, stem + "_camera.png")  # the untouched (rotated) photo
    cv2.imwrite(raw_path, frame, [int(cv2.IMWRITE_PNG_COMPRESSION), 1])

    debug_path = os.path.join(SAVE_DIR, scan_id, "debug", stem + "_film.jpg") if SAVE_DEBUG else None
    try:
        digital, info = atlas_preprocess.film_to_digital(frame, debug_path=debug_path)
    except Exception as exc:
        traceback.print_exc()
        return jsonify({'error': f'Film processing failed: {exc}'}), 500

    if REQUIRE_TISSUE and not info.get('usable'):
        return jsonify({'error': ' '.join(info.get('warnings') or ['No breast found in the photo.']),
                        'warnings': info.get('warnings', []), 'quality': info, 'raw_path': raw_path}), 422

    image_path = os.path.join(folder, stem + ".png")  # what the AI will see (16-bit, background = 0)
    cv2.imwrite(image_path, digital, [int(cv2.IMWRITE_PNG_COMPRESSION), 3])
    preview_path, _w, _h = _write_preview(image_path)

    return jsonify({
        'status': 'success',
        'source': 'camera',
        'image_path': image_path,  # Returns the nested path to Flutter
        'preview_path': preview_path,
        'raw_path': raw_path,
        'warnings': info.get('warnings', []),
        'quality': info,
    })


USB_PREFIX = "usb:"          # ids of files on a stick look like  usb:<stick name>/<path inside the stick>
MAX_FILES_PER_SOURCE = 4000  # a stick with more files than this is only searched in part (keeps the kiosk responsive)
MAX_LISTED = 200


def _unescape_mount_field(text):
    """/proc/mounts writes a space as \\040, a tab as \\011, a backslash as \\134, ..."""
    return re.sub(r'\\([0-7]{3})', lambda m: chr(int(m.group(1), 8)), text)


def _usb_volumes(mounts_text=None):
    """The removable volumes that are mounted right now: [{'name': 'MY_STICK', 'path': '/media/raspi/MY_STICK'}].

    A mount counts when it is a real block device (/dev/...) mounted one or two levels below a media folder
    (MEDIA_ROOTS), which is where the desktop's automounter puts a USB stick."""
    if mounts_text is None:
        try:
            with open('/proc/self/mounts', encoding='utf-8', errors='replace') as fh:
                mounts_text = fh.read()
        except OSError:
            return []
    roots = [os.path.realpath(r) for r in MEDIA_ROOTS]
    volumes, names = [], set()
    for line in mounts_text.splitlines():
        parts = line.split()
        if len(parts) < 2 or not parts[0].startswith('/dev/'):
            continue
        mount_point = os.path.normpath(_unescape_mount_field(parts[1]))
        for root in roots:
            rel = os.path.relpath(mount_point, root)
            if rel.startswith('..') or rel == '.' or rel.count(os.sep) > 1:
                continue
            name = os.path.basename(mount_point)
            unique, n = name, 2
            while unique in names:
                unique, n = f"{name} ({n})", n + 1
            names.add(unique)
            volumes.append({'name': unique, 'path': mount_point})
            break
    return volumes


def _skip_folder(name):
    return name.startswith(('.', '$')) or name.lower() in ('system volume information', 'lost+found')


def _walk_softcopy(base):
    """(modified time, full path, size) of the files below ``base`` (at most 3 folders deep), hidden files and files
    that are still being copied left out."""
    found = []
    for root, dirs, names in os.walk(base):
        depth = 0 if root == base else os.path.relpath(root, base).count(os.sep) + 1
        dirs[:] = [d for d in dirs if not _skip_folder(d)] if depth < 3 else []
        for name in names:
            if name.startswith('.') or name.lower().endswith(('.part', '.tmp', '.partial', '.crdownload')):
                continue  # hidden files and files that are still being transferred
            full = os.path.join(root, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                found.append((st.st_mtime, full, st.st_size))
        if len(found) >= MAX_FILES_PER_SOURCE:
            break
    return found


@app.route('/inbox', methods=['GET'])
def inbox():
    """The softcopy files the operator can pick: those on a plugged-in USB stick and those in the inbox folder,
    newest first.  Files on a stick that are not images (documents, videos, ...) are left out."""
    base = os.path.realpath(INBOX_DIR)
    os.makedirs(base, exist_ok=True)
    volumes = _usb_volumes()
    candidates = []     # (modified, full path, size, id the app sends back to /import, shown path, source, on a stick?)
    for mtime, full, size in _walk_softcopy(base):
        shown = os.path.relpath(full, base)
        candidates.append((mtime, full, size, shown, shown, 'Inbox', False))
    for vol in volumes:
        real = os.path.realpath(vol['path'])
        for mtime, full, size in _walk_softcopy(real):
            if os.path.islink(full):
                continue
            shown = os.path.relpath(full, real)
            candidates.append((mtime, full, size, USB_PREFIX + vol['name'] + '/' + shown, shown,
                               'USB: ' + vol['name'], True))
    candidates.sort(key=lambda item: item[0], reverse=True)
    files = []
    for mtime, full, size, file_id, shown, source, on_stick in candidates:
        if len(files) >= MAX_LISTED:
            break
        try:
            fmt = atlas_convert.sniff_format(full)
        except OSError:
            continue
        if on_stick and fmt == 'unknown':
            continue
        files.append({'path': file_id, 'display': shown, 'name': os.path.basename(full), 'size': size,
                      'modified': int(mtime), 'format': fmt, 'source': source})
    return jsonify({'inbox': base, 'volumes': [v['name'] for v in volumes], 'files': files})


def _resolve_softcopy(source_path):
    """The real path of a file the app picked (an inbox path, or  usb:<stick>/<path>),
    only if it lies inside the inbox folder or inside a stick that is mounted now."""
    if source_path.startswith(USB_PREFIX):
        name, _, rel = source_path[len(USB_PREFIX):].partition('/')
        for vol in _usb_volumes():
            if vol['name'] == name:
                if not rel:
                    raise ValueError('source_path is required.')
                return _inside(vol['path'], rel)
        raise ValueError('That USB stick is not connected any more. Plug it in again and refresh the list.')
    return _inside(INBOX_DIR, source_path)


@app.route('/import', methods=['POST'])
def import_softcopy():
    """Softcopy source: take a file from a USB stick (or the inbox) and make a PNG of it
    (DICOM -> PNG, PNG stays, other -> PNG)."""
    data = request.get_json(silent=True) or {}
    try:
        scan_id = _clean_scan_id(data.get('scan_id'))
        side = _clean_side(data.get('side'))
        view = _clean_view(data.get('view'))
        if not data.get('source_path'):
            raise ValueError('source_path is required.')
        source = _resolve_softcopy(str(data['source_path']))
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if not os.path.isfile(source):
        return jsonify({'error': 'File not found. If it is on a USB stick, check that the stick is still plugged in.'}), 404

    folder = os.path.join(SAVE_DIR, scan_id, side)
    stem = f"{side}_{view}_{int(time.time())}"
    try:
        conv = atlas_convert.convert_to_png(source, folder, stem=stem)
        preview_path, _w, _h = _write_preview(conv.png_path)
    except atlas_convert.ConversionError as exc:
        return jsonify({'error': str(exc)}), 422
    except Exception as exc:
        traceback.print_exc()
        return jsonify({'error': f'Could not import the file: {exc}'}), 500

    return jsonify({
        'status': 'success',
        'source': 'softcopy',
        'image_path': conv.png_path,
        'preview_path': preview_path,
        'source_name': os.path.basename(source),
        'source_format': conv.source_format,
        'converted': conv.converted,  # False = it already was a PNG and was kept as it is
        'bit_depth': conv.bit_depth,
        'width': conv.width,
        'height': conv.height,
        'warnings': conv.warnings,
    })


# ---------------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------------
BIRADS = ["BI-RADS 1", "BI-RADS 2", "BI-RADS 3", "BI-RADS 4", "BI-RADS 5"]
SIDE_NAME = {"L": "Left", "R": "Right"}

# The real 15-network ensemble (atlas_models.py) is used by default.  ATLAS_MOCK_MODELS=1 switches to the random
# placeholder below, ONLY for developing the app on a machine without PyTorch / the model files (every result is then
# labelled "MOCK RESULT").  If the real models cannot be loaded the analysis fails with an explanation; it never falls
# back to random numbers by itself.
MODELS_ARE_MOCK = _env_flag("ATLAS_MOCK_MODELS", False)

_RECOMMENDATION = {
    0: "Negative. Routine screening as per guidelines.",
    1: "Benign finding. Routine screening as per guidelines.",
    2: "Probably benign. Short-interval follow-up imaging is usually recommended.",
    3: "Suspicious abnormality. Tissue sampling (biopsy) should be considered.",
    4: "Highly suggestive of malignancy. Appropriate action (biopsy) should be taken.",
}


def run_models(slot_canvases, sides):
    """Runs the AI.

    slot_canvases: {('L','CC'): uint8[1280, 800], ('L','MLO'): ..., ('R','CC'): ..., ('R','MLO'): ...}
        always all four inputs, produced by atlas_preprocess.process_image + fill_slots (the same thing the
        training notebook's predict_exam_files feeds to the networks).
    sides: the sides ('L' / 'R') that have at least one real view; only these get a result.
    returns {'L': [P(B1), P(B2), P(B3), P(B4), P(B5)], 'R': [...]}  (each list sums to 1)

    Real mode: atlas_models.run_ensemble (15 networks, weighted average, see atlas_models.py).
    Mock mode (ATLAS_MOCK_MODELS=1): a random placeholder.
    """
    if not MODELS_ARE_MOCK:
        return atlas_models.run_ensemble(slot_canvases, sides)
    rng = np.random.default_rng()
    return {s: [float(x) for x in rng.dirichlet([6.0, 6.0, 1.2, 1.5, 0.6])] for s in sides}


def _format_result(probs):
    k = int(np.argmax(probs))
    return {
        'classification': BIRADS[k],
        'confidence': f"{100.0 * probs[k]:.1f}%",
        'probabilities': '  '.join(f"B{i + 1} {100.0 * p:.0f}%" for i, p in enumerate(probs)),
        'recommendation': ('MOCK RESULT: the AI models are not connected yet. Consult a healthcare provider for '
                           'next steps.' if MODELS_ARE_MOCK else _RECOMMENDATION[k]),
        '_k': k,
    }


@app.route('/analyze', methods=['POST'])
def analyze():
    """Run the AI on the views that were captured / imported (1 to 4 of them)."""
    data = request.get_json(silent=True) or {}
    try:
        scan_id = _clean_scan_id(data.get('scan_id'))
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    views = data.get('views')
    if not isinstance(views, list) or not views:
        return jsonify({'error': 'No views to analyse.'}), 400

    canvases = {}
    for item in views:
        try:
            side = _clean_side(item.get('side'))
            view = _clean_view(item.get('view'))
            path = _inside(SAVE_DIR, str(item.get('image_path') or ''))
        except (ValueError, AttributeError) as exc:
            return jsonify({'error': str(exc)}), 400
        res = atlas_preprocess.process_image(path)  # exactly the notebook's preprocessing
        if res is None:
            return jsonify({'error': f'Could not read the {side} {view} image.'}), 422
        canvases[(side[0], view)] = res[0]

    slots = atlas_preprocess.fill_slots({key: key for key in canvases})  # copies a missing view from a neighbour
    model_inputs = {slot: canvases[source] for slot, source in slots.items()}
    sides = sorted({side for side, _view in canvases})  # only breasts with at least one real view get a result
    # Report only the copies that influence a result.  A breast that was marked "not available" is still filled with
    # the other breast's views (the model always gets four inputs) but no result is produced for it.
    substituted = [f"{SIDE_NAME[s[0]]} {s[1]} <- {SIDE_NAME[src[0]]} {src[1]}"
                   for s, src in slots.items() if s != src and s[0] in sides]

    if SAVE_DEBUG:  # what the networks really get: handy for the thesis figures and for debugging
        out_dir = os.path.join(SAVE_DIR, scan_id, "model_input")
        os.makedirs(out_dir, exist_ok=True)
        for (side, view), canvas in model_inputs.items():
            cv2.imwrite(os.path.join(out_dir, f"{side}_{view}.png"), canvas)

    try:
        probs = run_models(model_inputs, sides)
    except Exception as exc:
        traceback.print_exc()
        return jsonify({'error': f'The AI models failed: {exc}'}), 500

    results = {SIDE_NAME[s]: _format_result(probs[s]) for s in sides}
    worst_side = max(results, key=lambda name: (results[name]['_k'], float(results[name]['confidence'].rstrip('%'))))
    combined = {k: v for k, v in results[worst_side].items() if k != '_k'}
    combined['basis'] = f"{worst_side} breast" if len(results) > 1 else f"{worst_side} breast only"
    for r in results.values():
        r.pop('_k', None)

    note = ''
    if substituted:
        note = ("A view was missing, so the AI used a copy of the other view of the same breast instead ("
                + ', '.join(substituted) + "). The result for that breast is less reliable.")
    return jsonify({
        'status': 'success',
        'mock': MODELS_ARE_MOCK,
        'results': results,
        'combined': combined,
        'note': note,
        'substituted': substituted,
    })


_init_camera()
if not MODELS_ARE_MOCK:
    atlas_models.preload_in_background()   # load the networks while the operator captures the views

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, threaded=True)
