"""Camera detection and what the operator sees when there is no picture (no real camera is used: fakes only)."""
import json
import os
import sys
import threading
import time
import types

import cv2
import numpy as np
import pytest

import app as backend


class FakeCapture:
    """Stands in for cv2.VideoCapture.  `frames` = how many frames it delivers before it stops (None = forever)."""
    opened_sources = []

    def __init__(self, source, api=None, opens=True, frames=None):
        self.source, self.opens, self.left = source, opens, frames
        self.props = {}
        FakeCapture.opened_sources.append(source)

    def isOpened(self):
        return self.opens

    def read(self):
        if not self.opens or self.left == 0:
            return False, None
        if self.left is not None:
            self.left -= 1
        return True, np.full((480, 640, 3), 90, np.uint8)

    def set(self, prop, value):
        self.props[prop] = value
        return True

    def get(self, prop):
        return self.props.get(prop, 640 if prop == cv2.CAP_PROP_FRAME_WIDTH else 480)

    def release(self):
        self.opens = False


@pytest.fixture(autouse=True)
def clean_camera(monkeypatch):
    """Every test starts without a camera, and the module's camera state is put back afterwards."""
    FakeCapture.opened_sources = []
    monkeypatch.setattr(backend, "camera", None)
    monkeypatch.setattr(backend, "USE_PICAMERA2", False)
    monkeypatch.setattr(backend, "CAMERA_BACKEND", "none")
    monkeypatch.setattr(backend, "CAMERA_INDEX", "")
    monkeypatch.setattr(backend, "CAMERA_STATUS", {"state": "starting", "detail": ""})
    monkeypatch.setattr(backend, "_camera_ok_detail", "")
    monkeypatch.setattr(backend, "_lock_opencv_exposure", lambda: None)
    monkeypatch.setattr(backend.sys, "platform", "linux")


def _no_picamera(monkeypatch):
    """Importing picamera2 fails, as on a PC."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "picamera2":
            raise ImportError("No module named 'picamera2'")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", fake_import)


def _text_of(frame_chunk):
    jpg = frame_chunk.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n", 1)[0]
    return cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)


# ----------------------------------------------------------------------------------------------- switched off
def test_camera_none_says_so_in_the_stream_and_in_health(monkeypatch):
    monkeypatch.setattr(backend, "CAMERA_MODE", "none")
    backend._init_camera()
    assert backend.CAMERA_STATUS["state"] == "off" and "ATLAS_CAMERA=none" in backend.CAMERA_STATUS["detail"]
    frame = _text_of(next(backend.generate_frames()))
    assert frame.shape[0] > frame.shape[1] or frame.size            # a real picture, not an empty reply
    assert (frame[..., 2] > 100).any() and (frame[..., 0] < 100).any()  # red heading + white explanation were drawn
    backend.app.config["TESTING"] = True
    j = backend.app.test_client().get("/health").get_json()
    assert j["camera"] == "none" and j["camera_status"]["state"] == "off"


# --------------------------------------------------------------------------------------------- a USB webcam
def _usb_cameras(monkeypatch, *nodes):
    """The system has exactly these USB cameras (the sysfs scan itself is tested further down)."""
    monkeypatch.setattr(backend, "_linux_usb_webcams", lambda: list(nodes))


def test_no_usb_camera_is_reported_clearly(monkeypatch):
    monkeypatch.setattr(backend, "CAMERA_MODE", "auto")
    _no_picamera(monkeypatch)
    _usb_cameras(monkeypatch)
    backend._init_camera()
    st = backend.CAMERA_STATUS
    assert st["state"] == "not_found" and "No USB camera found" in st["detail"] and backend.CAMERA_BACKEND == "none"
    assert "ATLAS_CAMERA_INDEX" in st["detail"]
    assert backend.read_frame() == (False, None)


def test_first_webcam_that_gives_a_picture_is_used(monkeypatch):
    monkeypatch.setattr(backend, "CAMERA_MODE", "auto")
    _no_picamera(monkeypatch)
    _usb_cameras(monkeypatch, "/dev/video0", "/dev/video1", "/dev/video2")
    # video0 opens but never delivers a picture; video1 does not open; video2 is the real one
    sources = {"/dev/video0": dict(frames=0), "/dev/video1": dict(opens=False), "/dev/video2": {}}
    monkeypatch.setattr(backend.cv2, "VideoCapture", lambda src, api=None: FakeCapture(src, api, **sources[src]))
    backend._init_camera()
    assert FakeCapture.opened_sources == ["/dev/video0", "/dev/video1", "/dev/video2"]
    assert backend.CAMERA_BACKEND == "opencv" and backend.CAMERA_STATUS["state"] == "ok"
    assert "/dev/video2" in backend.CAMERA_STATUS["detail"]
    ok, frame = backend.read_frame()
    assert ok and frame.shape[2] == 3


def test_a_forced_camera_is_the_only_one_tried(monkeypatch):
    monkeypatch.setattr(backend, "CAMERA_MODE", "auto")
    monkeypatch.setattr(backend, "CAMERA_INDEX", "3")
    _no_picamera(monkeypatch)
    _usb_cameras(monkeypatch, "/dev/video0")                               # ignored: the operator chose
    monkeypatch.setattr(backend.cv2, "VideoCapture", lambda src, api=None: FakeCapture(src, api))
    backend._init_camera()
    assert FakeCapture.opened_sources == [3] and backend.CAMERA_STATUS["state"] == "ok"


def test_a_forced_device_path_is_used_as_it_is(monkeypatch):
    monkeypatch.setattr(backend, "CAMERA_MODE", "auto")
    monkeypatch.setattr(backend, "CAMERA_INDEX", "/dev/video4")
    _no_picamera(monkeypatch)
    monkeypatch.setattr(backend.cv2, "VideoCapture", lambda src, api=None: FakeCapture(src, api))
    backend._init_camera()
    assert FakeCapture.opened_sources == ["/dev/video4"] and backend.CAMERA_STATUS["state"] == "ok"


def test_without_linux_the_first_indices_are_tried(monkeypatch):
    monkeypatch.setattr(backend, "CAMERA_MODE", "auto")
    monkeypatch.setattr(backend.sys, "platform", "darwin")
    _no_picamera(monkeypatch)
    sources = {0: dict(opens=False), 1: {}, 2: {}}
    monkeypatch.setattr(backend.cv2, "VideoCapture", lambda src, api=None: FakeCapture(src, api, **sources[src]))
    backend._init_camera()
    assert FakeCapture.opened_sources == [0, 1] and backend.CAMERA_STATUS["state"] == "ok"


def test_webcam_that_cannot_be_opened_lists_the_reason(monkeypatch):
    monkeypatch.setattr(backend, "CAMERA_MODE", "auto")
    _no_picamera(monkeypatch)
    _usb_cameras(monkeypatch, "/dev/video0")
    monkeypatch.setattr(backend.cv2, "VideoCapture", lambda src, api=None: FakeCapture(src, api, opens=False))
    backend._init_camera()
    st = backend.CAMERA_STATUS
    assert st["state"] == "not_found" and "/dev/video0 cannot be opened" in st["detail"] and "'video' group" in st["detail"]


def test_a_camera_that_stops_delivering_is_reported(monkeypatch):
    monkeypatch.setattr(backend, "CAMERA_MODE", "auto")
    _no_picamera(monkeypatch)
    _usb_cameras(monkeypatch, "/dev/video0")
    cams = []
    monkeypatch.setattr(backend.cv2, "VideoCapture", lambda src, api=None: cams.append(FakeCapture(src, api)) or cams[-1])
    backend._init_camera()
    assert backend.read_frame()[0] is True
    cams[0].left = 0                                                     # the cable is pulled out
    assert backend.read_frame() == (False, None)
    assert backend.CAMERA_STATUS["state"] == "read_failed"
    cams[0].left = None                                                  # and plugged in again
    assert backend.read_frame()[0] is True and backend.CAMERA_STATUS["state"] == "ok"


# ------------------------------------------------------- a driver that never answers must not block the start
class StuckCapture(FakeCapture):
    """A V4L2 node that opens and then blocks inside read() (what /dev/video21 did on the Pi: 10 s per try)."""
    release_it = threading.Event()

    def read(self):
        StuckCapture.release_it.wait(30)
        return False, None


@pytest.fixture()
def stuck_driver():
    StuckCapture.release_it = threading.Event()
    yield StuckCapture
    StuckCapture.release_it.set()                                        # lets the abandoned probe threads end


def test_a_stuck_driver_is_given_up_after_the_time_limit(monkeypatch, stuck_driver):
    monkeypatch.setattr(backend, "CAMERA_MODE", "auto")
    monkeypatch.setattr(backend, "WEBCAM_PROBE_TIMEOUT", 0.3)
    _no_picamera(monkeypatch)
    _usb_cameras(monkeypatch, "/dev/video0", "/dev/video2")
    sources = {"/dev/video0": StuckCapture, "/dev/video2": FakeCapture}
    monkeypatch.setattr(backend.cv2, "VideoCapture", lambda src, api=None: sources[src](src, api))
    started = time.monotonic()
    backend._init_camera()
    assert time.monotonic() - started < 5                                # not 10 s per read, not forever
    assert backend.CAMERA_STATUS["state"] == "ok" and "/dev/video2" in backend.CAMERA_STATUS["detail"]


def test_if_every_driver_is_stuck_the_message_says_so(monkeypatch, stuck_driver):
    monkeypatch.setattr(backend, "CAMERA_MODE", "auto")
    monkeypatch.setattr(backend, "WEBCAM_PROBE_TIMEOUT", 0.2)
    _no_picamera(monkeypatch)
    _usb_cameras(monkeypatch, "/dev/video0")
    monkeypatch.setattr(backend.cv2, "VideoCapture", lambda src, api=None: StuckCapture(src, api))
    started = time.monotonic()
    backend._init_camera()
    assert time.monotonic() - started < 5
    st = backend.CAMERA_STATUS
    assert st["state"] == "not_found" and "does not answer" in st["detail"] and "in use by another program" in st["detail"]


# ----------------------------------------------------------------------- which /dev/video nodes are cameras
def _fake_sysfs(tmp_path, monkeypatch, nodes):
    """nodes: {"videoN": (path of the device below /sys/devices, index)}.  Builds the same layout as /sys:
    /class/video4linux/videoN is a symlink into /devices/...  and glob() is pointed at it."""
    class_dir = tmp_path / "class" / "video4linux"
    os.makedirs(class_dir)
    for name, (device, index) in nodes.items():
        real = tmp_path / "devices" / device / "video4linux" / name
        os.makedirs(real)
        (real / "index").write_text(f"{index}\n")
        os.symlink(real, class_dir / name)
    monkeypatch.setattr(backend.glob, "glob", lambda pattern: sorted(str(p) for p in class_dir.iterdir()))


def test_only_usb_cameras_are_candidates_not_the_pis_internal_video_nodes(tmp_path, monkeypatch):
    """The log of the Pi 4 that hung: video14/video15/video21 are the Pi's own (codec, ISP, CSI) and are never touched."""
    _fake_sysfs(tmp_path, monkeypatch, {
        "video10": ("platform/soc/fe00b840.mailbox/bcm2835-codec", 0),
        "video14": ("platform/soc/fe801000.csi", 0),
        "video15": ("platform/soc/fe801000.csi", 0),
        "video21": ("platform/soc/fe801000.csi", 0),
        "video0": ("platform/scb/fd500000.pcie/pci0000:00/0000:00:00.0/0000:01:00.0/usb1/1-1/1-1.2/1-1.2:1.0", 0),
        "video1": ("platform/scb/fd500000.pcie/pci0000:00/0000:00:00.0/0000:01:00.0/usb1/1-1/1-1.2/1-1.2:1.0", 1),
    })
    assert backend._linux_usb_webcams() == ["/dev/video0"]               # video1 is the camera's metadata node


def test_usb_cameras_are_listed_in_numeric_order(tmp_path, monkeypatch):
    usb = "platform/soc/usb1/1-1/1-1:1.0"
    _fake_sysfs(tmp_path, monkeypatch, {"video10": (usb + "a", 0), "video2": (usb + "b", 0), "video3": (usb + "b", 1)})
    assert backend._linux_usb_webcams() == ["/dev/video2", "/dev/video10"]


def test_no_video_nodes_at_all(tmp_path, monkeypatch):
    monkeypatch.setattr(backend.glob, "glob", lambda pattern: [])
    assert backend._linux_usb_webcams() == []


# ---------------------------------------------------------------------------------------------- the Pi camera
def _fake_picamera2(monkeypatch, error):
    fake = types.ModuleType("picamera2")

    class Boom:
        def __init__(self):
            raise error
    fake.Picamera2 = Boom
    monkeypatch.setitem(sys.modules, "picamera2", fake)


def test_picamera_failure_is_named_when_the_webcam_fallback_fails_too(monkeypatch):
    """A Pi whose CSI camera cannot be opened: the message names Picamera2's own error."""
    _fake_picamera2(monkeypatch, RuntimeError("Camera frontend has timed out"))
    monkeypatch.setattr(backend, "CAMERA_MODE", "auto")
    _usb_cameras(monkeypatch)
    backend._init_camera()
    assert backend.CAMERA_STATUS["state"] == "not_found"
    assert "Camera frontend has timed out" in backend.CAMERA_STATUS["detail"]


def test_a_busy_pi_camera_says_who_probably_has_it(monkeypatch):
    """The real log: 'Camera __init__ sequence did not complete.' caused by 'Failed to acquire camera: Device or
    resource busy' -- another process (normally atlas-backend.service, started at boot) owns the camera."""
    try:
        try:
            raise RuntimeError("Failed to acquire camera: Device or resource busy")
        except RuntimeError as inner:
            raise RuntimeError("Camera __init__ sequence did not complete.") from inner
    except RuntimeError as outer:
        error = outer
    _fake_picamera2(monkeypatch, error)
    monkeypatch.setattr(backend, "CAMERA_MODE", "auto")
    _usb_cameras(monkeypatch)
    backend._init_camera()
    st = backend.CAMERA_STATUS
    assert st["state"] == "not_found"
    assert "in use by another program" in st["detail"]
    assert "sudo systemctl stop atlas-backend.service" in st["detail"]
    assert "Device or resource busy" not in st["detail"]                 # the operator reads advice, not libcamera jargon


def test_a_busy_pi_camera_falls_back_to_a_usb_camera_if_there_is_one(monkeypatch):
    _fake_picamera2(monkeypatch, RuntimeError("Failed to acquire camera: Device or resource busy"))
    monkeypatch.setattr(backend, "CAMERA_MODE", "auto")
    _usb_cameras(monkeypatch, "/dev/video0")
    monkeypatch.setattr(backend.cv2, "VideoCapture", lambda src, api=None: FakeCapture(src, api))
    backend._init_camera()
    assert backend.CAMERA_STATUS["state"] == "ok" and "/dev/video0" in backend.CAMERA_STATUS["detail"]
