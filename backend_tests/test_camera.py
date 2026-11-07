"""Camera detection and what the operator sees when there is no picture (no real camera is used: fakes only)."""
import json

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
def test_no_video_device_is_reported_clearly(monkeypatch):
    monkeypatch.setattr(backend, "CAMERA_MODE", "auto")
    _no_picamera(monkeypatch)
    monkeypatch.setattr(backend.glob, "glob", lambda pattern: [])
    backend._init_camera()
    st = backend.CAMERA_STATUS
    assert st["state"] == "not_found" and "No /dev/video*" in st["detail"] and backend.CAMERA_BACKEND == "none"
    assert backend.read_frame() == (False, None)


def test_first_webcam_that_gives_a_picture_is_used(monkeypatch):
    monkeypatch.setattr(backend, "CAMERA_MODE", "auto")
    _no_picamera(monkeypatch)
    monkeypatch.setattr(backend.glob, "glob", lambda pattern: ["/dev/video2", "/dev/video0", "/dev/video1"])
    # video0 is a metadata node (opens, never delivers a picture); video1 does not open; video2 is the real one
    sources = {"/dev/video0": dict(frames=0), "/dev/video1": dict(opens=False), "/dev/video2": {}}
    monkeypatch.setattr(backend.cv2, "VideoCapture", lambda src, api=None: FakeCapture(src, api, **sources[src]))
    backend._init_camera()
    assert FakeCapture.opened_sources == ["/dev/video0", "/dev/video1", "/dev/video2"]    # numeric order
    assert backend.CAMERA_BACKEND == "opencv" and backend.CAMERA_STATUS["state"] == "ok"
    assert "/dev/video2" in backend.CAMERA_STATUS["detail"]
    ok, frame = backend.read_frame()
    assert ok and frame.shape[2] == 3


def test_a_forced_camera_is_the_only_one_tried(monkeypatch):
    monkeypatch.setattr(backend, "CAMERA_MODE", "auto")
    monkeypatch.setattr(backend, "CAMERA_INDEX", "3")
    _no_picamera(monkeypatch)
    monkeypatch.setattr(backend.cv2, "VideoCapture", lambda src, api=None: FakeCapture(src, api))
    backend._init_camera()
    assert FakeCapture.opened_sources == [3] and backend.CAMERA_STATUS["state"] == "ok"


def test_webcam_that_cannot_be_opened_lists_the_reason(monkeypatch):
    monkeypatch.setattr(backend, "CAMERA_MODE", "auto")
    _no_picamera(monkeypatch)
    monkeypatch.setattr(backend.glob, "glob", lambda pattern: ["/dev/video0"])
    monkeypatch.setattr(backend.cv2, "VideoCapture", lambda src, api=None: FakeCapture(src, api, opens=False))
    backend._init_camera()
    st = backend.CAMERA_STATUS
    assert st["state"] == "not_found" and "/dev/video0 cannot be opened" in st["detail"] and "'video' group" in st["detail"]


def test_a_camera_that_stops_delivering_is_reported(monkeypatch):
    monkeypatch.setattr(backend, "CAMERA_MODE", "auto")
    _no_picamera(monkeypatch)
    monkeypatch.setattr(backend.glob, "glob", lambda pattern: ["/dev/video0"])
    cams = []
    monkeypatch.setattr(backend.cv2, "VideoCapture", lambda src, api=None: cams.append(FakeCapture(src, api)) or cams[-1])
    backend._init_camera()
    assert backend.read_frame()[0] is True
    cams[0].left = 0                                                     # the cable is pulled out
    assert backend.read_frame() == (False, None)
    assert backend.CAMERA_STATUS["state"] == "read_failed"
    cams[0].left = None                                                  # and plugged in again
    assert backend.read_frame()[0] is True and backend.CAMERA_STATUS["state"] == "ok"


def test_picamera_failure_is_named_when_the_webcam_fallback_fails_too(monkeypatch):
    """A Pi whose CSI camera cannot be opened: the message names Picamera2's own error."""
    import sys
    import types
    fake = types.ModuleType("picamera2")

    class Boom:
        def __init__(self):
            raise RuntimeError("Camera frontend has timed out")
    fake.Picamera2 = Boom
    monkeypatch.setitem(sys.modules, "picamera2", fake)
    monkeypatch.setattr(backend, "CAMERA_MODE", "auto")
    monkeypatch.setattr(backend.glob, "glob", lambda pattern: [])
    backend._init_camera()
    assert backend.CAMERA_STATUS["state"] == "not_found"
    assert "Camera frontend has timed out" in backend.CAMERA_STATUS["detail"]
