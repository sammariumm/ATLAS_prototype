import json
import os

import cv2
import numpy as np
import pytest

import synth
from dicom_utils import write_dicom

os.environ["ATLAS_CAMERA"] = "none"
import app as backend  # noqa: E402  (must come after the env var)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "SAVE_DIR", str(tmp_path / "scans"))
    monkeypatch.setattr(backend, "INBOX_DIR", str(tmp_path / "inbox"))
    os.makedirs(backend.INBOX_DIR)
    backend.app.config["TESTING"] = True
    return backend.app.test_client()


def _photo(**kw):
    """What the camera would deliver (already rotated): a portrait photo of a film on a lightbox."""
    return synth.make_film_photo(synth.make_digital(), **kw)


def _camera_returns(monkeypatch, frame):
    monkeypatch.setattr(backend, "read_frame", lambda: (True, frame.copy()))


def _post(client, url, **body):
    r = client.post(url, data=json.dumps(body), content_type="application/json")
    return r.status_code, r.get_json()


# ----------------------------------------------------------------------------------------------- camera ----
def test_rotation_is_90_degrees_counter_clockwise_by_default():
    assert backend.CAMERA_ROTATION == 90
    frame = np.zeros((4, 6, 3), np.uint8)             # landscape: 4 rows x 6 columns
    frame[0, 0] = (255, 255, 255)                      # marker in the top-left corner
    rot = backend.rotate_frame(frame)
    assert rot.shape == (6, 4, 3)                      # now portrait
    assert rot[5, 0].tolist() == [255, 255, 255]       # CCW: top-left goes to bottom-left
    assert rot.sum() == 255 * 3


@pytest.mark.parametrize("deg,shape,corner", [(0, (4, 6), (0, 0)), (90, (6, 4), (5, 0)),
                                              (180, (4, 6), (3, 5)), (270, (6, 4), (0, 3))])
def test_rotation_setting(monkeypatch, deg, shape, corner):
    monkeypatch.setattr(backend, "CAMERA_ROTATION", deg)
    frame = np.zeros((4, 6, 3), np.uint8)
    frame[0, 0] = 255
    rot = backend.rotate_frame(frame)
    assert rot.shape[:2] == shape and rot[corner].tolist() == [255, 255, 255]


def test_preview_stream_keeps_the_portrait_aspect(monkeypatch):
    frame = np.zeros((1640, 1232, 3), np.uint8)       # portrait frame after rotation
    monkeypatch.setattr(backend, "read_frame", lambda: (True, frame))
    chunk = next(backend.generate_frames())
    jpg = chunk.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n", 1)[0]
    img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
    assert img.shape[0] == 640 and img.shape[0] > img.shape[1]
    assert abs(img.shape[1] / img.shape[0] - 1232 / 1640) < 0.01      # not stretched


def test_preview_stream_shows_error_frame_when_camera_fails(monkeypatch):
    monkeypatch.setattr(backend, "read_frame", lambda: (False, None))
    monkeypatch.setattr(backend.time, "sleep", lambda s: None)
    chunk = next(backend.generate_frames())
    assert chunk.startswith(b"--frame")


class FakePicam:
    """Records what the backend asks libcamera to do."""
    def __init__(self, md):
        self.md, self.controls = md, None

    def capture_metadata(self):
        return dict(self.md)

    def set_controls(self, c):
        self.controls = dict(c)
        self.md = dict(self.md, ExposureTime=c["ExposureTime"], AnalogueGain=c["AnalogueGain"])


def test_auto_exposure_is_switched_off_and_frozen(monkeypatch):
    monkeypatch.setattr(backend.time, "sleep", lambda s: None)
    cam = FakePicam({"ExposureTime": 12000, "AnalogueGain": 1.2, "ColourGains": (1.9, 1.4)})
    monkeypatch.setattr(backend, "picam2", cam)
    monkeypatch.setattr(backend, "EXPOSURE_US", 0)
    monkeypatch.setattr(backend, "ANALOGUE_GAIN", 0.0)
    monkeypatch.setattr(backend, "LOCK_AWB", False)
    backend._lock_picamera_exposure()
    assert cam.controls["AeEnable"] is False
    assert cam.controls["ExposureTime"] == 12000 and cam.controls["AnalogueGain"] == 1.2   # frozen at what AE chose
    assert "AwbEnable" not in cam.controls


def test_fixed_exposure_from_environment_settings(monkeypatch):
    monkeypatch.setattr(backend.time, "sleep", lambda s: None)
    cam = FakePicam({"ExposureTime": 12000, "AnalogueGain": 1.2, "ColourGains": (1.9, 1.4)})
    monkeypatch.setattr(backend, "picam2", cam)
    monkeypatch.setattr(backend, "EXPOSURE_US", 60000)
    monkeypatch.setattr(backend, "ANALOGUE_GAIN", 1.0)
    monkeypatch.setattr(backend, "LOCK_AWB", True)
    backend._lock_picamera_exposure()
    assert cam.controls["ExposureTime"] == 60000 and cam.controls["AnalogueGain"] == 1.0
    assert cam.controls["FrameDurationLimits"][0] >= 60000          # long exposure needs a longer frame time
    assert cam.controls["AwbEnable"] is False and cam.controls["ColourGains"] == (1.9, 1.4)
    assert backend.EXPOSURE_STATE["auto_exposure"] is False


def test_exposure_lock_failure_does_not_crash(monkeypatch):
    class Broken(FakePicam):
        def set_controls(self, c):
            raise RuntimeError("libcamera said no")
    monkeypatch.setattr(backend.time, "sleep", lambda s: None)
    monkeypatch.setattr(backend, "picam2", Broken({"ExposureTime": 1, "AnalogueGain": 1.0}))
    backend._lock_picamera_exposure()            # must only log


def test_still_is_the_mean_of_several_frames(monkeypatch):
    frames = iter([np.full((4, 4, 3), v, np.uint8) for v in (10, 20, 30, 40)])
    monkeypatch.setattr(backend, "read_frame", lambda: (True, next(frames)))
    assert backend.grab_still(4).mean() == 25
    monkeypatch.setattr(backend, "read_frame", lambda: (False, None))
    assert backend.grab_still(3) is None


def test_health(client):
    j = client.get("/health").get_json()
    assert j["rotation_ccw_deg"] == 90 and j["models"] == "mock"


# ---------------------------------------------------------------------------------------------- /capture ----
def test_capture_saves_photo_digital_image_and_preview(client, monkeypatch):
    _camera_returns(monkeypatch, _photo())
    code, j = _post(client, "/capture", scan_id="SCAN-0007", side="Left", view="CC")
    assert code == 200 and j["status"] == "success" and j["source"] == "camera"
    img = cv2.imread(j["image_path"], cv2.IMREAD_UNCHANGED)
    assert img.dtype == np.uint16 and img.max() > 0               # digital-like, ready for process_image
    assert cv2.imread(j["raw_path"]).shape[:2] == (1640, 1232)      # the untouched photo is kept too
    assert cv2.imread(j["preview_path"], cv2.IMREAD_UNCHANGED).dtype == np.uint8
    assert os.sep.join(["SCAN-0007", "Left"]) in j["image_path"]
    assert j["quality"]["usable"] and j["warnings"] == []
    assert any(f.endswith("_film.jpg") for f in os.listdir(os.path.join(backend.SAVE_DIR, "SCAN-0007", "debug")))


def test_capture_result_goes_through_process_image(client, monkeypatch):
    import atlas_preprocess as ap
    _camera_returns(monkeypatch, _photo())
    _, j = _post(client, "/capture", scan_id="S1", side="Right", view="MLO")
    canvas, info = ap.process_image(j["image_path"])
    assert canvas.shape == (1280, 800) and canvas.max() > 100 and canvas[:, :4].max() > 0


def test_capture_without_a_film_is_rejected(client, monkeypatch):
    _camera_returns(monkeypatch, np.full((1640, 1232, 3), 235, np.uint8))
    code, j = _post(client, "/capture", scan_id="S1", side="Left", view="CC")
    assert code == 422 and "film" in j["error"].lower() and j["quality"]["usable"] is False


def test_capture_rejection_can_be_switched_off(client, monkeypatch):
    monkeypatch.setattr(backend, "REQUIRE_TISSUE", False)
    _camera_returns(monkeypatch, np.full((1640, 1232, 3), 235, np.uint8))
    code, j = _post(client, "/capture", scan_id="S1", side="Left", view="CC")
    assert code == 200 and j["warnings"]


def test_capture_hardware_failure(client, monkeypatch):
    monkeypatch.setattr(backend, "read_frame", lambda: (False, None))
    code, j = _post(client, "/capture", scan_id="S1", side="Left", view="CC")
    assert code == 500 and "capture" in j["error"].lower()


@pytest.mark.parametrize("body", [
    dict(scan_id="../../etc", side="Left", view="CC"),
    dict(scan_id="S1", side="Middle", view="CC"),
    dict(scan_id="S1", side="Left", view="XYZ"),
    dict(scan_id="a b", side="Left", view="CC"),
])
def test_capture_rejects_bad_input(client, monkeypatch, body):
    _camera_returns(monkeypatch, _photo())
    code, j = _post(client, "/capture", **body)
    assert code == 400 and "error" in j
    assert not os.path.exists(backend.SAVE_DIR) or os.listdir(backend.SAVE_DIR) == []


# ------------------------------------------------------------------------------------------ /inbox, /import ---
def _fill_inbox():
    inbox = backend.INBOX_DIR
    write_dicom(os.path.join(inbox, "exam1.dcm"), (synth.make_digital(300, 220).astype(np.uint16) * 15))
    cv2.imwrite(os.path.join(inbox, "scan.png"), synth.make_digital(300, 220))
    cv2.imwrite(os.path.join(inbox, "photo.jpg"), synth.make_digital(300, 220))
    os.makedirs(os.path.join(inbox, "patient42"))
    cv2.imwrite(os.path.join(inbox, "patient42", "R_MLO.bmp"), synth.make_digital(300, 220))
    open(os.path.join(inbox, "partial.png.part"), "wb").write(b"123")
    open(os.path.join(inbox, ".hidden"), "wb").write(b"123")


def test_inbox_lists_files_with_detected_format(client):
    _fill_inbox()
    j = client.get("/inbox").get_json()
    by_name = {f["name"]: f for f in j["files"]}
    assert set(by_name) == {"exam1.dcm", "scan.png", "photo.jpg", "R_MLO.bmp"}     # no .part, no hidden
    assert by_name["exam1.dcm"]["format"] == "dicom" and by_name["scan.png"]["format"] == "png"
    assert by_name["R_MLO.bmp"]["path"] == os.path.join("patient42", "R_MLO.bmp")


def test_inbox_empty(client):
    assert client.get("/inbox").get_json()["files"] == []


def test_import_dicom_becomes_png(client):
    _fill_inbox()
    code, j = _post(client, "/import", scan_id="S9", side="Left", view="CC", source_path="exam1.dcm")
    assert code == 200 and j["source_format"] == "dicom" and j["converted"] is True
    img = cv2.imread(j["image_path"], cv2.IMREAD_UNCHANGED)
    assert j["image_path"].endswith(".png") and img.dtype == np.uint16
    assert cv2.imread(j["preview_path"], cv2.IMREAD_UNCHANGED).dtype == np.uint8


def test_import_png_stays_the_same_png(client):
    _fill_inbox()
    code, j = _post(client, "/import", scan_id="S9", side="Right", view="CC", source_path="scan.png")
    assert code == 200 and j["converted"] is False and j["source_format"] == "png"
    assert open(j["image_path"], "rb").read() == open(os.path.join(backend.INBOX_DIR, "scan.png"), "rb").read()


@pytest.mark.parametrize("name,fmt", [("photo.jpg", "jpeg"), (os.path.join("patient42", "R_MLO.bmp"), "bmp")])
def test_import_other_formats_become_png(client, name, fmt):
    _fill_inbox()
    code, j = _post(client, "/import", scan_id="S9", side="Left", view="MLO", source_path=name)
    assert code == 200 and j["source_format"] == fmt and j["converted"] is True
    assert open(j["image_path"], "rb").read(8) == b"\x89PNG\r\n\x1a\n"


def test_import_cannot_read_outside_the_inbox(client, tmp_path):
    secret = tmp_path / "secret.png"
    cv2.imwrite(str(secret), synth.make_digital(100, 80))
    for bad in ("../secret.png", str(secret), "/etc/passwd"):
        code, j = _post(client, "/import", scan_id="S9", side="Left", view="CC", source_path=bad)
        assert code == 400, bad


def test_import_errors(client):
    _fill_inbox()
    assert _post(client, "/import", scan_id="S9", side="Left", view="CC", source_path="nope.dcm")[0] == 404
    open(os.path.join(backend.INBOX_DIR, "junk.bin"), "wb").write(os.urandom(500))
    code, j = _post(client, "/import", scan_id="S9", side="Left", view="CC", source_path="junk.bin")
    assert code == 422 and j["error"]
    assert _post(client, "/import", scan_id="S9", side="Left", view="CC")[0] == 400


# ---------------------------------------------------------------------------------------------- /analyze ----
def _png(client, name, side, view, digital):
    cv2.imwrite(os.path.join(backend.INBOX_DIR, name), digital)
    return _post(client, "/import", scan_id="S5", side=side, view=view, source_path=name)[1]


def test_analyze_all_four_views(client):
    views = []
    for side, view, seed in (("Left", "CC", 1), ("Left", "MLO", 2), ("Right", "CC", 3), ("Right", "MLO", 4)):
        r = _png(client, f"{side}{view}.png", side, view, synth.make_digital(side=side[0], seed=seed))
        views.append(dict(side=side, view=view, image_path=r["image_path"]))
    code, j = _post(client, "/analyze", scan_id="S5", views=views)
    assert code == 200 and j["mock"] is True
    assert set(j["results"]) == {"Left", "Right"} and j["note"] == "" and j["substituted"] == []
    for res in list(j["results"].values()) + [j["combined"]]:
        assert res["classification"].startswith("BI-RADS ") and res["confidence"].endswith("%")
        assert "MOCK" in res["recommendation"]
    inputs = os.path.join(backend.SAVE_DIR, "S5", "model_input")
    assert sorted(os.listdir(inputs)) == ["L_CC.png", "L_MLO.png", "R_CC.png", "R_MLO.png"]
    assert cv2.imread(os.path.join(inputs, "L_CC.png"), cv2.IMREAD_UNCHANGED).shape == (1280, 800)


def test_analyze_one_side_only_reports_only_that_side(client):
    views = []
    for view, seed in (("CC", 1), ("MLO", 2)):
        r = _png(client, f"L{view}.png", "Left", view, synth.make_digital(seed=seed))
        views.append(dict(side="Left", view=view, image_path=r["image_path"]))
    code, j = _post(client, "/analyze", scan_id="S5", views=views)
    assert code == 200 and list(j["results"]) == ["Left"]
    # both Left views are real; the Right slots are filled for the model but no result (or warning) is made for them
    assert j["substituted"] == [] and j["note"] == ""
    assert j["combined"]["classification"] == j["results"]["Left"]["classification"]
    assert j["combined"]["basis"] == "Left breast only"


def test_analyze_single_view_substitutes_the_other_view(client):
    r = _png(client, "x.png", "Right", "MLO", synth.make_digital(side="R"))
    code, j = _post(client, "/analyze", scan_id="S5", views=[dict(side="Right", view="MLO", image_path=r["image_path"])])
    assert code == 200 and list(j["results"]) == ["Right"]
    assert j["substituted"] == ["Right CC <- Right MLO"]
    assert "less reliable" in j["note"] and "Right CC <- Right MLO" in j["note"]


def test_analyze_camera_capture_end_to_end(client, monkeypatch):
    _camera_returns(monkeypatch, _photo())
    _, cap = _post(client, "/capture", scan_id="S6", side="Left", view="CC")
    code, j = _post(client, "/analyze", scan_id="S6", views=[dict(side="Left", view="CC", image_path=cap["image_path"])])
    assert code == 200 and "Left" in j["results"]


def test_analyze_combined_is_the_worse_breast(client, monkeypatch):
    views = []
    for side in ("Left", "Right"):
        r = _png(client, f"{side}.png", side, "CC", synth.make_digital(side=side[0]))
        views.append(dict(side=side, view="CC", image_path=r["image_path"]))
    monkeypatch.setattr(backend, "run_models", lambda inputs, sides: {"L": [.9, .05, .02, .02, .01], "R": [.02, .03, .05, .8, .1]})
    code, j = _post(client, "/analyze", scan_id="S5", views=views)
    assert j["results"]["Left"]["classification"] == "BI-RADS 1"
    assert j["results"]["Right"]["classification"] == "BI-RADS 4"
    assert j["combined"]["classification"] == "BI-RADS 4" and "Right" in j["combined"]["basis"]


def test_analyze_gets_the_four_notebook_inputs(client, monkeypatch):
    seen = {}

    def fake(inputs, sides):
        seen["keys"] = sorted(inputs)
        seen["shapes"] = {k: (v.shape, v.dtype) for k, v in inputs.items()}
        return {s: [.2] * 5 for s in sides}
    monkeypatch.setattr(backend, "run_models", fake)
    r = _png(client, "a.png", "Left", "CC", synth.make_digital())
    _post(client, "/analyze", scan_id="S5", views=[dict(side="Left", view="CC", image_path=r["image_path"])])
    assert seen["keys"] == [("L", "CC"), ("L", "MLO"), ("R", "CC"), ("R", "MLO")]
    assert all(v == ((1280, 800), np.uint8) for v in seen["shapes"].values())


def test_analyze_errors(client, tmp_path):
    assert _post(client, "/analyze", scan_id="S5", views=[])[0] == 400
    assert _post(client, "/analyze", scan_id="S5")[0] == 400
    assert _post(client, "/analyze", scan_id="S5", views=["x"])[0] == 400
    outside = tmp_path / "o.png"
    cv2.imwrite(str(outside), synth.make_digital(100, 80))
    assert _post(client, "/analyze", scan_id="S5", views=[dict(side="Left", view="CC", image_path=str(outside))])[0] == 400
    os.makedirs(backend.SAVE_DIR, exist_ok=True)
    bad = os.path.join(backend.SAVE_DIR, "bad.png")
    open(bad, "wb").write(b"nope")
    code, j = _post(client, "/analyze", scan_id="S5", views=[dict(side="Left", view="CC", image_path=bad)])
    assert code == 422 and "Left CC" in j["error"]


def test_analyze_model_failure_is_reported(client, monkeypatch):
    def boom(inputs, sides):
        raise RuntimeError("out of memory")
    monkeypatch.setattr(backend, "run_models", boom)
    r = _png(client, "a.png", "Left", "CC", synth.make_digital())
    code, j = _post(client, "/analyze", scan_id="S5", views=[dict(side="Left", view="CC", image_path=r["image_path"])])
    assert code == 500 and "out of memory" in j["error"]
