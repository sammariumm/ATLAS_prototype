import os

import cv2
import numpy as np
import pytest

import atlas_convert as ac
from dicom_utils import write_dicom
import synth


def _digital12(h=300, w=220, seed=0):
    """12-bit-looking array: zero background + tissue up to 4000."""
    d = synth.make_digital(h, w, seed=seed).astype(np.float32) / 255.0
    return np.rint(d * 4000).astype(np.uint16)


def _read(path):
    return cv2.imread(str(path), cv2.IMREAD_UNCHANGED)


def test_dicom_mono2_goes_to_16bit_png(tmp_path):
    arr = _digital12()
    src = tmp_path / "a.dcm"
    write_dicom(src, arr)
    res = ac.convert_to_png(str(src), str(tmp_path / "out"), stem="L_CC")
    png = _read(res.png_path)
    assert res.source_format == "dicom" and res.converted and res.bit_depth == 16
    assert png.dtype == np.uint16 and png.shape == arr.shape
    assert png.max() == 65535 and np.all(png[arr == 0] == 0)          # background stays exactly 0
    assert np.corrcoef(png.ravel(), arr.ravel())[0, 1] > 0.9999        # linear scaling only
    assert os.path.basename(res.png_path) == "L_CC.png"


def test_dicom_monochrome1_is_inverted_so_background_is_black(tmp_path):
    arr = _digital12()
    mono1 = (arr.max() - arr).astype(np.uint16)                        # MONOCHROME1: air = high value
    src = tmp_path / "m1.dcm"
    write_dicom(src, mono1, photometric="MONOCHROME1")
    res = ac.convert_to_png(str(src), str(tmp_path / "out"))
    png = _read(res.png_path)
    assert np.all(png[arr == 0] == 0)
    assert np.corrcoef(png.ravel(), arr.ravel())[0, 1] > 0.9999


def test_dicom_rescale_slope_and_intercept_are_applied(tmp_path):
    arr = _digital12()
    stored = (arr + 1000).astype(np.uint16)                            # stored = real + 1000
    src = tmp_path / "r.dcm"
    write_dicom(src, stored, slope=1, intercept=-1000, bits_stored=16)
    res = ac.convert_to_png(str(src), str(tmp_path / "out"))
    png = _read(res.png_path)
    assert res.warnings == []
    assert np.all(png[arr == 0] == 0)                                  # without the LUT the background would be 1000


def test_dicom_8bit_option(tmp_path):
    arr = _digital12()
    src = tmp_path / "e.dcm"
    write_dicom(src, arr)
    res = ac.convert_to_png(str(src), str(tmp_path / "out"), dicom_bits=8)
    png = _read(res.png_path)
    assert res.bit_depth == 8 and png.dtype == np.uint8 and png.max() == 255 and np.all(png[arr == 0] == 0)


def test_dicom_env_switches(tmp_path, monkeypatch):
    arr = _digital12()
    src = tmp_path / "e.dcm"
    write_dicom(src, arr)
    monkeypatch.setenv("ATLAS_DICOM_PNG_BITS", "8")
    assert _read(ac.convert_to_png(str(src), str(tmp_path / "o1")).png_path).dtype == np.uint8
    monkeypatch.setenv("ATLAS_DICOM_PNG_BITS", "16")
    assert _read(ac.convert_to_png(str(src), str(tmp_path / "o2")).png_path).dtype == np.uint16


def test_dicom_rle_compressed(tmp_path):
    from pydicom.uid import RLELossless
    arr = _digital12()
    src = tmp_path / "rle.dcm"
    write_dicom(src, arr, compress=RLELossless)
    png = _read(ac.convert_to_png(str(src), str(tmp_path / "out")).png_path)
    assert png.shape == arr.shape and np.all(png[arr == 0] == 0)


def test_dicom_jpeg2000_compressed(tmp_path):
    from pydicom.uid import JPEG2000Lossless
    arr = _digital12()
    src = tmp_path / "j2k.dcm"
    try:
        write_dicom(src, arr, compress=JPEG2000Lossless)
    except Exception as exc:                       # no J2K encoder installed: nothing to test
        pytest.skip(f"cannot create a JPEG-2000 DICOM here: {exc}")
    png = _read(ac.convert_to_png(str(src), str(tmp_path / "out")).png_path)
    assert png.shape == arr.shape and np.array_equal(png == 0, arr == 0)


def test_dicom_multiframe_uses_middle_frame_and_warns(tmp_path):
    a = _digital12()
    stack = np.stack([a // 4, a, a // 2])
    src = tmp_path / "dbt.dcm"
    write_dicom(src, stack, frames=3)
    res = ac.convert_to_png(str(src), str(tmp_path / "out"))
    assert any("Multi-frame" in w for w in res.warnings)
    assert _read(res.png_path).shape == a.shape


def test_dicom_detected_by_content_not_extension(tmp_path):
    arr = _digital12()
    src = tmp_path / "really_dicom.png"            # a DICOM wearing a .png name
    write_dicom(src, arr)
    res = ac.convert_to_png(str(src), str(tmp_path / "out"))
    assert res.source_format == "dicom" and res.converted


def test_png_stays_png_byte_for_byte(tmp_path):
    img = synth.make_digital(200, 150)
    src = tmp_path / "x.dcm"                        # a PNG wearing a .dcm name
    cv2.imwrite(str(src.with_suffix(".png")), img)
    os.replace(src.with_suffix(".png"), src)
    res = ac.convert_to_png(str(src), str(tmp_path / "out"), stem="R_MLO")
    assert res.source_format == "png" and not res.converted
    assert open(res.png_path, "rb").read() == open(src, "rb").read()    # not re-encoded


def test_16bit_png_stays_16bit(tmp_path):
    img = (synth.make_digital(200, 150).astype(np.uint16) * 200)
    src = tmp_path / "deep.png"
    cv2.imwrite(str(src), img)
    res = ac.convert_to_png(str(src), str(tmp_path / "out"))
    assert res.bit_depth == 16 and np.array_equal(_read(res.png_path), img)


@pytest.mark.parametrize("ext,fmt", [(".jpg", "jpeg"), (".bmp", "bmp"), (".tif", "tiff")])
def test_other_formats_become_png(tmp_path, ext, fmt):
    img = synth.make_digital(240, 180)
    src = tmp_path / ("photo" + ext)
    cv2.imwrite(str(src), img)
    res = ac.convert_to_png(str(src), str(tmp_path / "out"))
    png = _read(res.png_path)
    assert res.source_format == fmt and res.converted
    assert open(res.png_path, "rb").read(8) == b"\x89PNG\r\n\x1a\n"
    assert png.shape[:2] == img.shape[:2]
    if ext != ".jpg":                                # lossless formats must come back identical
        assert np.array_equal(png if png.ndim == 2 else png[:, :, 0], img)


def test_16bit_tiff_keeps_its_depth(tmp_path):
    img = (synth.make_digital(100, 80).astype(np.uint16) * 250)
    src = tmp_path / "deep.tif"
    cv2.imwrite(str(src), img)
    res = ac.convert_to_png(str(src), str(tmp_path / "out"))
    assert res.bit_depth == 16 and np.array_equal(_read(res.png_path), img)


def test_colour_jpeg_is_kept_as_colour_png(tmp_path):
    bgr = cv2.merge([synth.make_digital(100, 80)] * 3)
    src = tmp_path / "c.jpg"
    cv2.imwrite(str(src), bgr)
    png = _read(ac.convert_to_png(str(src), str(tmp_path / "out")).png_path)
    assert png.ndim == 3 and png.shape[2] == 3


def test_pillow_fallback_for_gif(tmp_path):
    PIL = pytest.importorskip("PIL.Image")
    src = tmp_path / "g.gif"
    PIL.fromarray(synth.make_digital(60, 50)).save(src)
    res = ac.convert_to_png(str(src), str(tmp_path / "out"))
    assert res.source_format == "gif" and _read(res.png_path).shape[:2] == (60, 50)


def test_garbage_empty_and_missing_files_raise(tmp_path):
    junk = tmp_path / "junk.dat"
    junk.write_bytes(os.urandom(2000))
    with pytest.raises(ac.ConversionError):
        ac.convert_to_png(str(junk), str(tmp_path / "out"))
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")
    with pytest.raises(ac.ConversionError):
        ac.convert_to_png(str(empty), str(tmp_path / "out"))
    with pytest.raises(ac.ConversionError):
        ac.convert_to_png(str(tmp_path / "nope.dcm"), str(tmp_path / "out"))


def test_truncated_png_raises(tmp_path):
    good = tmp_path / "g.png"
    cv2.imwrite(str(good), synth.make_digital(100, 80))
    bad = tmp_path / "bad.png"
    bad.write_bytes(good.read_bytes()[:60])
    with pytest.raises(ac.ConversionError):
        ac.convert_to_png(str(bad), str(tmp_path / "out"))


def test_dicom_without_pixel_data_raises(tmp_path):
    arr = _digital12()
    src = tmp_path / "np.dcm"
    ds = write_dicom(src, arr)
    del ds.PixelData
    try:
        ds.save_as(str(src), enforce_file_format=True)
    except TypeError:
        ds.save_as(str(src), write_like_original=False)
    with pytest.raises(ac.ConversionError, match="no image"):
        ac.convert_to_png(str(src), str(tmp_path / "out"))


def test_names_never_collide(tmp_path):
    src = tmp_path / "a.png"
    cv2.imwrite(str(src), synth.make_digital(50, 40))
    out = str(tmp_path / "out")
    p1 = ac.convert_to_png(str(src), out, stem="same").png_path
    p2 = ac.convert_to_png(str(src), out, stem="same").png_path
    assert p1 != p2 and os.path.exists(p1) and os.path.exists(p2)
