import cv2
import numpy as np
import pytest

import atlas_preprocess as ap
import synth

IMG_H, IMG_W, USE_CLAHE = ap.IMG_H, ap.IMG_W, ap.USE_CLAHE


# --- the notebook's cell-2 functions, copied verbatim as the reference ----------------------------------------
def notebook_process_image(path):
    cv2.setNumThreads(1)
    raw = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if raw is None:
        return None
    if raw.ndim == 3:
        raw = cv2.cvtColor(raw, cv2.COLOR_BGRA2GRAY if raw.shape[2] == 4 else cv2.COLOR_BGR2GRAY)
    png_h, png_w = raw.shape
    if raw.dtype != np.uint8:                                  # 12/16-bit → 8-bit (same as the old Cell 4)
        f = raw.astype(np.float32)
        nz = f[f > 0]
        if nz.size > 0:
            p2, p98 = np.percentile(nz, (2, 98))
            f = np.clip(f, p2, p98)
        raw = ((f - f.min()) / (f.max() - f.min() + 1e-8) * 255.0).astype(np.uint8)

    binary = (raw > 5).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if n > 1:
        lab = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        x0, y0, w, h = [int(v) for v in stats[lab, :4]]
        mask = (labels[y0:y0 + h, x0:x0 + w] == lab).astype(np.uint8)
        crop = raw[y0:y0 + h, x0:x0 + w] * mask
    else:
        x0, y0, h, w = 0, 0, png_h, png_w
        mask, crop = binary, raw
    if USE_CLAHE:
        crop = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(crop) * mask

    half = max(1, w // 2)                                      # chest wall = the side with more tissue
    flipped = bool(mask[:, w - half:].sum() > mask[:, :half].sum())
    if flipped:
        crop = crop[:, ::-1]

    s = min(IMG_H / h, IMG_W / w)
    nh, nw = max(1, min(IMG_H, int(round(h * s)))), max(1, min(IMG_W, int(round(w * s))))
    res = cv2.resize(np.ascontiguousarray(crop), (nw, nh),
                     interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
    canvas = np.zeros((IMG_H, IMG_W), np.uint8)
    canvas[:nh, :nw] = res
    return canvas, {"png_h": png_h, "png_w": png_w, "x0": x0, "y0": y0, "cw": w, "ch": h,
                    "flipped": flipped, "scale": float(s)}


def notebook_fill_slots(have):
    out = {}
    for side in ("L", "R"):
        cc, mlo = have.get((side, "CC")), have.get((side, "MLO"))
        if cc is None and mlo is None:
            continue
        out[(side, "CC")] = cc if cc is not None else mlo
        out[(side, "MLO")] = mlo if mlo is not None else cc
    if not out:
        return None
    for side, other in (("L", "R"), ("R", "L")):
        if (side, "CC") not in out:
            out[(side, "CC")], out[(side, "MLO")] = out[(other, "CC")], out[(other, "MLO")]
    return out


def _same(path):
    a, b = ap.process_image(path), notebook_process_image(path)
    assert a is not None and b is not None
    assert np.array_equal(a[0], b[0])
    assert a[1] == b[1]


@pytest.fixture(params=["L", "R"])
def digital(request):
    return synth.make_digital(side=request.param, seed=5)


def test_process_image_equals_notebook_uint8(tmp_path, digital):
    p = tmp_path / "a.png"
    cv2.imwrite(str(p), digital)
    _same(p)


def test_process_image_equals_notebook_uint16_with_noisy_background(tmp_path, digital):
    rng = np.random.default_rng(0)
    img = digital.astype(np.float32) * 230 + rng.integers(0, 40, digital.shape)   # air is not exactly 0
    img[:5] = 0
    p = tmp_path / "b.png"
    cv2.imwrite(str(p), np.clip(img, 0, 65535).astype(np.uint16))
    _same(p)


def test_process_image_equals_notebook_colour_and_alpha(tmp_path, digital):
    bgr = cv2.merge([digital] * 3)
    p3 = tmp_path / "c3.png"
    cv2.imwrite(str(p3), bgr)
    _same(p3)
    bgra = cv2.merge([digital] * 3 + [np.full_like(digital, 255)])
    p4 = tmp_path / "c4.png"
    cv2.imwrite(str(p4), bgra)
    _same(p4)


def test_process_image_blank_image_equals_notebook(tmp_path):
    p = tmp_path / "z.png"
    cv2.imwrite(str(p), np.zeros((300, 200), np.uint8))
    _same(p)


def test_process_image_unreadable_returns_none(tmp_path):
    assert ap.process_image(tmp_path / "missing.png") is None
    junk = tmp_path / "junk.png"
    junk.write_bytes(b"not an image")
    assert ap.process_image(junk) is None


def test_process_image_output_contract(tmp_path):
    p = tmp_path / "a.png"
    cv2.imwrite(str(p), synth.make_digital())
    canvas, info = ap.process_image(p)
    assert canvas.shape == (1280, 800) and canvas.dtype == np.uint8
    assert info["flipped"] is False and canvas[:, :5].max() > 0         # chest wall on the left after processing
    cv2.imwrite(str(p), synth.make_digital(side="R"))
    canvas_r, info_r = ap.process_image(p)
    assert info_r["flipped"] is True and canvas_r[:, :5].max() > 0       # a right breast is flipped to the left


@pytest.mark.parametrize("have", [
    {},
    {("L", "CC"): "a"},
    {("L", "MLO"): "a"},
    {("R", "CC"): "a", ("R", "MLO"): "b"},
    {("L", "CC"): "a", ("R", "MLO"): "b"},
    {("L", "CC"): "a", ("L", "MLO"): "b", ("R", "CC"): "c"},
    {("L", "CC"): "a", ("L", "MLO"): "b", ("R", "CC"): "c", ("R", "MLO"): "d"},
])
def test_fill_slots_equals_notebook(have):
    assert ap.fill_slots(have) == notebook_fill_slots(have)


def test_fill_slots_semantics():
    out = ap.fill_slots({("L", "CC"): "x"})
    assert out == {("L", "CC"): "x", ("L", "MLO"): "x", ("R", "CC"): "x", ("R", "MLO"): "x"}
    assert ap.fill_slots({}) is None


# --- film-on-lightbox front end (synthetic photographs) -----------------------------------------------------
def _compare(digital, photo, cfg=None):
    """Run film front end + process_array and compare with process_array of the true digital image."""
    out, info = ap.film_to_digital(photo, cfg or ap.FilmConfig())
    A, ia = ap.process_array(out)
    B, ib = ap.process_array(digital.astype(np.uint16) * 257)
    ma, mb = A > 0, B > 0
    iou = float((ma & mb).sum()) / max(1, int((ma | mb).sum()))
    a = cv2.GaussianBlur(A.astype(np.float32), (0, 0), 6)
    b = cv2.GaussianBlur(B.astype(np.float32), (0, 0), 6)
    best = -1.0
    for dx in range(-32, 33, 4):           # the front end trims a thin strip at the film edge -> allow a small shift
        for dy in range(-32, 33, 8):
            a2 = cv2.warpAffine(a, np.float32([[1, 0, dx], [0, 1, dy]]), (a.shape[1], a.shape[0]))
            m = (a2 > 0) | (b > 0)
            best = max(best, float(np.corrcoef(a2[m], b[m])[0, 1]))
    return iou, best, ia, ib, info


CASES = {
    "baseline": dict(),
    "rotated_and_shifted": dict(angle=-4.0, offset=(25, -30)),
    "clear_margin_bright": dict(margin_px=28),
    "clear_margin_dim": dict(margin_px=28, margin_level=0.70),
    "veiling_glare": dict(glare=0.04),
    "dark_enclosure": dict(enclosure=True),
    "dark_enclosure_and_margin": dict(enclosure=True, margin_px=24),
    "dim_lightbox": dict(lightbox=190.0),
    "noisy_sensor": dict(noise=5.0),
    "saturated_lightbox": dict(lightbox=255.0, tissue_max=0.9),
    "small_film_in_frame": dict(fill=0.55),
}


@pytest.mark.parametrize("side", ["L", "R"])
@pytest.mark.parametrize("name", sorted(CASES))
def test_film_photo_matches_digital(name, side):
    d = synth.make_digital(side=side, seed=2 if side == "L" else 3)
    photo = synth.make_film_photo(d, **CASES[name])
    iou, corr, ia, ib, info = _compare(d, photo)
    assert info["usable"], info
    assert iou > 0.90, (name, iou)
    assert corr > 0.75, (name, corr)
    assert ia["flipped"] == ib["flipped"]                     # chest-wall side recognised correctly
    assert info["film_found"]
    assert not [w for w in info["warnings"] if "could not be removed" in w or "No breast" in w]


def test_film_filling_the_frame_without_visible_lightbox():
    d = synth.make_digital()
    photo = synth.make_film_photo(d, angle=0.0, fill=1.0, vignette=0.0, frame_hw=d.shape)
    iou, corr, ia, ib, info = _compare(d, photo)
    assert iou > 0.95 and corr > 0.9 and info["usable"]


def test_output_background_is_exactly_zero_and_uint16():
    d = synth.make_digital()
    out, info = ap.film_to_digital(synth.make_film_photo(d))
    assert out.dtype == np.uint16 and out.max() > 1000
    border = np.concatenate([out[:5].ravel(), out[-5:].ravel(), out[:, -5:].ravel()])
    assert border.max() == 0                                   # no lightbox / film edge left at the border
    # the dtype is what makes process_image take the 16-bit branch (percentile stretch)
    canvas, _ = ap.process_array(out)
    assert canvas.max() > 200


@pytest.mark.parametrize("name,frame", [
    ("blank lightbox, no film", np.full((1640, 1232, 3), 235, np.uint8)),
    ("camera covered", np.full((1640, 1232, 3), 4, np.uint8)),
])
def test_no_film_is_reported_not_usable(name, frame):
    out, info = ap.film_to_digital(frame)
    assert not info["usable"] and info["warnings"] and out.max() == 0


def test_black_film_without_tissue_is_not_usable():
    out, info = ap.film_to_digital(synth.make_film_photo(np.zeros((1400, 1000), np.uint8)))
    assert not info["usable"]


def test_16bit_camera_frames_are_accepted():
    d = synth.make_digital()
    photo8 = synth.make_film_photo(d)
    out, info = ap.film_to_digital(photo8.astype(np.uint16) * 257)
    assert info["usable"] and info["film_found"]


def test_grayscale_frames_are_accepted():
    d = synth.make_digital()
    out, info = ap.film_to_digital(synth.make_film_photo(d)[:, :, 0])
    assert info["usable"]


def test_roi_from_environment(monkeypatch):
    monkeypatch.setenv("ATLAS_FILM_ROI", "10, 20, 1000, 1500")
    cfg = ap.FilmConfig.from_env()
    assert cfg.roi == (10, 20, 1000, 1500)
    monkeypatch.setenv("ATLAS_FILM_ROI", "garbage")
    assert ap.FilmConfig.from_env().roi is None
    d = synth.make_digital()
    photo = synth.make_film_photo(d)
    out, info = ap.film_to_digital(photo, ap.FilmConfig(roi=(10, 20, 1100, 1500)))
    assert info["usable"]


def test_debug_picture_is_written(tmp_path):
    d = synth.make_digital()
    dbg = tmp_path / "dbg" / "x.jpg"
    ap.film_to_digital(synth.make_film_photo(d), debug_path=str(dbg))
    img = cv2.imread(str(dbg))
    assert img is not None and img.shape[0] == 420 and img.shape[1] > 800


def test_info_is_json_serialisable():
    import json
    d = synth.make_digital()
    _, info = ap.film_to_digital(synth.make_film_photo(d, margin_px=28))
    json.dumps(info)


def test_make_preview_downsizes_and_is_8bit(tmp_path):
    big = (synth.make_digital(3000, 2200).astype(np.uint16) * 250)
    src = tmp_path / "big.png"
    cv2.imwrite(str(src), big)
    w, h = ap.make_preview(str(src), str(tmp_path / "p.jpg"))
    assert (w, h) == (2200, 3000)
    img = cv2.imread(str(tmp_path / "p.jpg"), cv2.IMREAD_UNCHANGED)
    assert img.dtype == np.uint8 and max(img.shape[:2]) == 1280
    with pytest.raises(ValueError):
        ap.make_preview(str(tmp_path / "missing.png"), str(tmp_path / "q.jpg"))
