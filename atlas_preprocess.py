"""
ATLAS-BC image preprocessing.

Two layers live here:

1. ``process_image`` / ``process_array`` / ``fill_slots``
   The notebook's preprocessing, ported unchanged (cell 2 of the training
   notebook).  The models were trained on exactly this output, so do NOT
   "improve" these functions -- any change silently shifts the model's input.
   The only difference to the notebook: ``cv2.setNumThreads(1)`` is left out
   (it is a process-wide setting meant for dataloader workers).

2. ``film_to_digital``
   A front end for PHOTOGRAPHS OF FILM ON A LIGHTBOX.  ``process_image``
   assumes a digital mammogram: black background (value 0), breast brighter.
   A camera photo of a film has a bright lightbox around the film and a
   not-quite-black film background, so ``process_image`` would treat the whole
   frame as "breast".  ``film_to_digital`` finds the film, removes the
   lightbox, estimates the film's black level and returns a "digital-like"
   16-bit image (background exactly 0) that ``process_image`` can take.

   It was written without real photographs of your lightbox.  Use the debug
   images (see ``save_debug``) to check it on real captures and tune the
   ``FilmConfig`` values / ``ATLAS_FILM_*`` environment variables if needed.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

# --------------------------------------------------------------------------
# Constants shared with the training notebook (cell 1)
# --------------------------------------------------------------------------
IMG_H, IMG_W = 1280, 800
USE_CLAHE = True
SLOTS = [("L", "CC"), ("L", "MLO"), ("R", "CC"), ("R", "MLO")]


# --------------------------------------------------------------------------
# 1. Notebook preprocessing (verbatim logic)
# --------------------------------------------------------------------------
def to_uint8(raw: np.ndarray) -> np.ndarray:
    """12/16-bit -> 8-bit exactly as the notebook does it (percentile 2..98 of the non-zero pixels)."""
    if raw.dtype != np.uint8:
        f = raw.astype(np.float32)
        nz = f[f > 0]
        if nz.size > 0:
            p2, p98 = np.percentile(nz, (2, 98))
            f = np.clip(f, p2, p98)
        raw = ((f - f.min()) / (f.max() - f.min() + 1e-8) * 255.0).astype(np.uint8)
    return raw


def process_array(raw: np.ndarray):
    """Image array -> breast crop (largest component) -> CLAHE -> chest wall on the LEFT -> resized in
    proportion onto an IMG_H x IMG_W black canvas.  Returns (uint8 canvas, info dict)."""
    if raw.ndim == 3:
        raw = cv2.cvtColor(raw, cv2.COLOR_BGRA2GRAY if raw.shape[2] == 4 else cv2.COLOR_BGR2GRAY)
    png_h, png_w = raw.shape
    raw = to_uint8(raw)

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

    half = max(1, w // 2)  # chest wall = the side with more tissue
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


def process_image(path):
    """PNG file -> (uint8 canvas, info dict), or None if the file cannot be read."""
    raw = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if raw is None:
        return None
    return process_array(raw)


def fill_slots(have):
    """have: {(side, view): value}.  Returns all 4 slots; a missing view is replaced by the other view of the
    same breast, a missing breast by the other breast.  None if nothing is available."""
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


# --------------------------------------------------------------------------
# 2. Film-on-lightbox front end
# --------------------------------------------------------------------------
def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


@dataclass
class FilmConfig:
    """Tunable values of the film front end (every ``*_frac`` is relative to the image side named in its comment)."""
    roi: Optional[Tuple[int, int, int, int]] = None  # (x, y, w, h) in pixels of the (rotated) camera frame
    lightbox_rel: float = 0.70    # lightbox / clear film = smooth areas brighter than this fraction of the lightbox level
    min_lightbox_frac: float = 0.01  # the lightbox must cover at least this share of the frame to be trusted
    min_film_frac: float = 0.08   # the film must cover at least this share of the frame
    margin_frac: float = 0.006    # (long side of the frame) grow the lightbox mask by this much: kills the film's bright edge / halo
    inset_frac: float = 0.008     # (short side of the film) then shrink the film by this much: kills the film's cut edge
    black_k: float = 4.0          # tissue = brighter than black level + black_k * noise
    min_noise: float = 1.5        # lower bound of the noise estimate (grey levels, 0..255 scale)

    @classmethod
    def from_env(cls) -> "FilmConfig":
        cfg = cls()
        roi = os.environ.get("ATLAS_FILM_ROI", "").strip()
        if roi:
            try:
                x, y, w, h = [int(float(v)) for v in roi.replace(";", ",").split(",")]
                if w > 0 and h > 0:
                    cfg.roi = (x, y, w, h)
            except ValueError:
                print(f">>> ignoring ATLAS_FILM_ROI={roi!r} (expected 'x,y,w,h')", flush=True)
        cfg.lightbox_rel = _env_float("ATLAS_FILM_LIGHTBOX_REL", cfg.lightbox_rel)
        cfg.margin_frac = _env_float("ATLAS_FILM_MARGIN", cfg.margin_frac)
        cfg.inset_frac = _env_float("ATLAS_FILM_INSET", cfg.inset_frac)
        cfg.black_k = _env_float("ATLAS_FILM_BLACK_K", cfg.black_k)
        return cfg


def _to_gray_f32(img: np.ndarray) -> np.ndarray:
    """Any camera array -> float32 grey image on a 0..255 scale."""
    a = np.asarray(img)
    if a.ndim == 3:
        a = cv2.cvtColor(a, cv2.COLOR_BGRA2GRAY if a.shape[2] == 4 else cv2.COLOR_BGR2GRAY)
    g = a.astype(np.float32)
    if a.dtype == np.uint16:
        g *= 255.0 / 65535.0
    elif a.dtype != np.uint8:
        g = g / max(float(g.max()), 1e-6) * 255.0
    return g


def _otsu_from_hist(hist: np.ndarray) -> int:
    p = hist / max(1.0, float(hist.sum()))
    omega = np.cumsum(p)
    mu = np.cumsum(p * np.arange(256))
    mt = mu[-1]
    denom = omega * (1.0 - omega)
    denom[denom == 0] = np.nan
    between = (mt * omega - mu) ** 2 / denom
    if np.all(np.isnan(between)):
        return 127
    return int(np.nanargmax(between))


def _black_level(vals: np.ndarray, min_noise: float) -> Tuple[float, float]:
    """Film background level and its noise, from the grey values inside the film.

    The film background (air) is the tallest peak of the dark half of the histogram.
    """
    hist = np.bincount(np.clip(vals, 0, 255).astype(np.uint8), minlength=256).astype(np.float64)
    smooth = np.convolve(hist, np.ones(5) / 5.0, mode="same")
    t = _otsu_from_hist(hist)
    b = float(np.argmax(smooth[: max(2, t + 1)]))
    near = vals[(vals >= b - 12.0) & (vals <= b + 12.0)]
    if near.size < 50:
        noise = 2.0
    else:
        noise = 1.4826 * float(np.median(np.abs(near - np.median(near))))
    return b, float(np.clip(noise, min_noise, 8.0))


def _find_lightbox(blur: np.ndarray, cfg: FilmConfig):
    """Lightbox = large, smooth, bright area.  Returns (level, bool mask) or None if there is none in view."""
    h, w = blur.shape
    level = float(np.percentile(blur, 99.0))
    if level < 100.0:  # a lightbox is bright; if nothing in view is, there is no lightbox
        return None
    cand = (blur >= cfg.lightbox_rel * level).astype(np.uint8)
    cand = cv2.morphologyEx(cand, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    # the lightbox is smooth, tissue is textured: measure the local standard deviation
    m1 = cv2.blur(blur, (9, 9))
    m2 = cv2.blur(blur * blur, (9, 9))
    local_std = np.sqrt(np.maximum(m2 - m1 * m1, 0.0))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(cand, connectivity=8)
    keep = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < 0.004 * h * w:
            continue
        if float(np.median(local_std[lab == i])) <= 0.035 * level:
            keep[i] = True
    mask = keep[lab]
    if float(mask.mean()) < cfg.min_lightbox_frac:
        return None
    return level, mask


def _order_quad(pts: np.ndarray) -> np.ndarray:
    """4 corner points -> top-left, top-right, bottom-right, bottom-left (for a roughly upright rectangle)."""
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    s = pts.sum(axis=1)
    d = pts[:, 0] - pts[:, 1]
    return np.array([pts[np.argmin(s)], pts[np.argmax(d)], pts[np.argmax(s)], pts[np.argmin(d)]], dtype=np.float32)


def _find_film_quad(lb_grown: np.ndarray, cfg: FilmConfig):
    """The film = the biggest non-lightbox region (preferably one that does not touch the frame border).
    Returns (corner points TL,TR,BR,BL, region mask) or None."""
    h, w = lb_grown.shape
    film = (~lb_grown).astype(np.uint8)
    film = cv2.morphologyEx(film, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(film, connectivity=8)
    best, best_score = None, None
    for i in range(1, n):
        x, y, bw, bh, area = [int(v) for v in stats[i, :5]]
        if area < cfg.min_film_frac * h * w:
            continue
        touches = x <= 1 or y <= 1 or x + bw >= w - 1 or y + bh >= h - 1
        score = (0 if touches else 1, area)
        if best_score is None or score > best_score:
            best, best_score = i, score
    if best is None:
        return None
    region = lab == best
    contours = cv2.findContours(region.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[-2]
    if not contours:
        return None
    cnt = max(contours, key=cv2.contourArea)
    rect = cv2.minAreaRect(cv2.convexHull(cnt))
    quad = _order_quad(cv2.boxPoints(rect))
    wd = 0.5 * (np.linalg.norm(quad[1] - quad[0]) + np.linalg.norm(quad[2] - quad[3]))
    hd = 0.5 * (np.linalg.norm(quad[3] - quad[0]) + np.linalg.norm(quad[2] - quad[1]))
    if min(wd, hd) < 16:
        return None
    aspect = min(wd, hd) / max(wd, hd)
    fill = float(region.sum()) / max(1.0, wd * hd)
    if aspect < 0.55 or fill < 0.70:  # not film-shaped: the outline is unclear
        return None
    return quad, region


def _segment(gs: np.ndarray, g_film: np.ndarray, ok: np.ndarray, cfg: FilmConfig, inset_frac: float):
    """Shrink the film area by ``inset_frac``, estimate the black level there and cut out the tissue."""
    h, w = ok.shape
    inset = max(1, int(round(inset_frac * min(h, w))))
    ki = 2 * inset + 1
    valid = cv2.erode(ok.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_RECT, (ki, ki))) > 0
    if int(valid.sum()) < 100:
        return None
    vals = g_film[valid]
    b, noise = _black_level(vals, cfg.min_noise)
    thr = b + max(cfg.black_k * noise, 6.0)
    fg = valid & (gs > thr)
    ko = max(3, 2 * int(round(0.005 * min(h, w))) + 1)  # ~0.5% of the film: removes specks and thin bright lines
    fg = cv2.morphologyEx(fg.astype(np.uint8), cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ko, ko))) > 0
    return {"valid": valid, "vals": vals, "b": b, "noise": noise, "fg": fg, "inset": inset}


def _edge_slab(a: np.ndarray, side: str, depth: int, step: int) -> np.ndarray:
    """A slab of thickness ``step`` lying ``depth`` pixels inside one edge of the film (central 90% of the edge)."""
    h, w = a.shape
    c0, r0 = int(0.05 * w), int(0.05 * h)
    if side == "top":
        return a[depth:depth + step, c0:w - c0]
    if side == "bottom":
        return a[h - depth - step:h - depth, c0:w - c0]
    if side == "left":
        return a[r0:h - r0, depth:depth + step]
    return a[r0:h - r0, w - depth - step:w - depth]


def _strip_uniform_edges(gs: np.ndarray, fg: np.ndarray, inset: int):
    """Cut off clear film margins: a band along a film edge that is bright AND uniform.  Tissue is textured, and
    the air next to the tissue is dark, so neither is touched.  Returns (new fg, {side: cut depth in px})."""
    h, w = fg.shape
    step = max(2, int(round(0.01 * min(h, w))))
    max_depth = inset + int(0.12 * min(h, w))
    out = fg.copy()
    cuts = {}
    for side in ("top", "bottom", "left", "right"):
        depth = inset
        while depth + step <= max_depth:
            sfg = _edge_slab(fg, side, depth, step)
            if sfg.size == 0 or float(sfg.mean()) < 0.85:
                break
            vals = _edge_slab(gs, side, depth, step)[sfg]
            if vals.size == 0 or float(vals.std()) > 0.06 * max(float(vals.mean()), 1.0):
                break
            depth += step
        if depth > inset:
            depth += step  # also remove the soft edge between the margin and the dark film
            cuts[side] = depth
            if side == "top":
                out[:depth, :] = False
            elif side == "bottom":
                out[h - depth:, :] = False
            elif side == "left":
                out[:, :depth] = False
            else:
                out[:, w - depth:] = False
    return out, cuts


def _frame_like(fg: np.ndarray, inset: int, frac: float = 0.7) -> bool:
    """True when 'tissue' runs along ALL FOUR edges of the film: that is a bright border (clear film margin,
    stray light), not a breast."""
    h, w = fg.shape
    d = max(3, int(round(0.02 * min(h, w))))
    a = inset
    strips = (fg[a:a + d, a:w - a], fg[h - a - d:h - a, a:w - a], fg[a:h - a, a:a + d], fg[a:h - a, w - a - d:w - a])
    return all(s.size > 0 and float(s.mean()) >= frac for s in strips)


def film_to_digital(img: np.ndarray, cfg: Optional[FilmConfig] = None,
                    debug_path: Optional[str] = None):
    """Photograph of a film on a lightbox -> 'digital-like' image.

    Returns ``(digital, info)``.  ``digital`` is uint16: background exactly 0, tissue > 0 (so it takes the same
    branch of ``process_image`` as a 16-bit PNG: percentile stretch, then crop/CLAHE/flip).
    ``info`` holds diagnostics and a list of human-readable ``warnings``.
    """
    cfg = cfg or FilmConfig.from_env()
    warnings: List[str] = []
    g_all = _to_gray_f32(img)
    H0, W0 = g_all.shape
    ox = oy = 0
    g = g_all
    if cfg.roi:
        x, y, rw, rh = cfg.roi
        x, y = max(0, min(x, W0 - 2)), max(0, min(y, H0 - 2))
        rw, rh = max(2, min(rw, W0 - x)), max(2, min(rh, H0 - y))
        g = g_all[y:y + rh, x:x + rw]
        ox, oy = x, y
    h, w = g.shape
    blur = cv2.GaussianBlur(g, (0, 0), max(1.0, 0.002 * max(h, w)))

    info: Dict = {"frame_w": int(W0), "frame_h": int(H0), "lightbox_found": False, "film_found": False,
                  "lightbox_level": None, "lightbox_pct": 0.0, "film_w": None, "film_h": None,
                  "tilt_deg": None, "black_level": None, "noise": None, "tissue_pct": 0.0, "usable": False,
                  "notes": []}

    lightbox = _find_lightbox(blur, cfg)
    lb_grown = np.zeros((h, w), dtype=bool)
    quad = None
    g_film, ok = g, np.ones((h, w), dtype=bool)  # ok = the film area (before it is shrunk by the inset)

    if lightbox is None:
        info["notes"].append("Lightbox not found in the picture; the whole frame was used as the film "
                             "(fine if the film fills the view).")
    else:
        level, lb_mask = lightbox
        info.update(lightbox_found=True, lightbox_level=round(level, 1), lightbox_pct=round(100.0 * float(lb_mask.mean()), 1))
        margin = max(2, int(round(cfg.margin_frac * max(h, w))))
        k = 2 * margin + 1
        lb_grown = cv2.dilate(lb_mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0
        found = _find_film_quad(lb_grown, cfg)
        if found is None:
            ok = ~lb_grown
            if int(ok.sum()) > 100:
                warnings.append("Could not find the outline of the film; everything that is not lightbox was used. "
                                "Check that the film lies fully on the lightbox (or set ATLAS_FILM_ROI).")
        else:
            quad, region = found
            wd = 0.5 * (np.linalg.norm(quad[1] - quad[0]) + np.linalg.norm(quad[2] - quad[3]))
            hd = 0.5 * (np.linalg.norm(quad[3] - quad[0]) + np.linalg.norm(quad[2] - quad[1]))
            dw, dh = int(round(wd)), int(round(hd))
            dst = np.array([[0, 0], [dw - 1, 0], [dw - 1, dh - 1], [0, dh - 1]], dtype=np.float32)
            M = cv2.getPerspectiveTransform(quad, dst)
            g_film = cv2.warpPerspective(g, M, (dw, dh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            ok = cv2.warpPerspective(region.astype(np.uint8) * 255, M, (dw, dh), flags=cv2.INTER_NEAREST) > 0
            d = quad[1] - quad[0]
            info.update(film_found=True, film_w=dw, film_h=dh,
                        tilt_deg=round(float(np.degrees(np.arctan2(d[1], d[0]))), 2))

    gs = cv2.GaussianBlur(g_film, (0, 0), 1.0)
    seg, used_frac = None, cfg.inset_frac
    for frac in (cfg.inset_frac, 0.02, 0.035, 0.05, 0.075, 0.10):
        cand = _segment(gs, g_film, ok, cfg, frac)
        if cand is None:
            break
        cand["fg"], cuts = _strip_uniform_edges(gs, cand["fg"], cand["inset"])
        cand["cuts"] = cuts
        seg, used_frac = cand, frac
        if not _frame_like(cand["fg"], cand["inset"]):
            break
    if seg is None:
        warnings.append("No film found in the picture. Put the film on the lightbox and try again.")
        info["warnings"] = warnings
        return np.zeros(g_film.shape, np.uint16), info
    if seg.get("cuts"):
        warnings.append("A clear film margin was cut off (%s)." % ", ".join(sorted(seg["cuts"])))
    if used_frac > cfg.inset_frac:
        if _frame_like(seg["fg"], seg["inset"]):
            warnings.append("A bright border around the film could not be removed; the result may be wrong. "
                            "Check the debug picture and ATLAS_FILM_ROI / ATLAS_FILM_INSET.")
        else:
            warnings.append("A bright border (clear film margin or stray light) was cut off.")

    valid, vals, b, noise, fg = seg["valid"], seg["vals"], seg["b"], seg["noise"], seg["fg"]
    scale = 65535.0 / max(1.0, 255.0 - b)
    digital = np.where(fg, np.clip((gs - b) * scale, 1.0, 65535.0), 0.0).astype(np.uint16)

    tissue_pct = 100.0 * float(fg.sum()) / max(1, int(valid.sum()))
    sat_pct = 100.0 * float((vals >= 253.0).mean())
    info.update(black_level=round(b, 1), noise=round(noise, 2), tissue_pct=round(tissue_pct, 1),
                saturated_pct=round(sat_pct, 2), inset_pct=round(100.0 * used_frac, 1))
    info["usable"] = tissue_pct >= 3.0
    if tissue_pct < 3.0:
        warnings.append("No breast tissue found. Is a film on the lightbox, and is the exposure right?")
    elif tissue_pct > 92.0:
        warnings.append("Almost the whole film looks bright; the lightbox mask or exposure may be off.")
    if sat_pct > 2.0:
        warnings.append("Parts of the film are over-exposed (saturated). Lower ATLAS_EXPOSURE_US.")
    if b > 60.0:
        warnings.append("The film background is quite bright (black level %.0f). Check for stray light or "
                        "over-exposure." % b)
    info["warnings"] = warnings

    if debug_path:
        try:
            save_debug(debug_path, g_all, (ox, oy), lb_grown, quad, g_film, digital)
        except Exception as exc:  # debugging aid only: never break a capture because of it
            print(">>> could not write film debug image:", exc, flush=True)
    return digital, info


def _fit_height(img: np.ndarray, height: int) -> np.ndarray:
    h, w = img.shape[:2]
    return cv2.resize(img, (max(1, int(round(w * height / h))), height), interpolation=cv2.INTER_AREA)


def save_debug(path: str, g_all: np.ndarray, offset: Tuple[int, int], lb_grown: np.ndarray,
               quad: Optional[np.ndarray], g_film: np.ndarray, digital: np.ndarray, height: int = 420) -> None:
    """Write one JPEG with 4 panels: photo + detected film outline | lightbox mask | rectified film | what the model gets."""
    ox, oy = offset
    base = cv2.cvtColor(np.clip(g_all, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    h, w = lb_grown.shape
    p1 = base.copy()
    cv2.rectangle(p1, (ox, oy), (ox + w - 1, oy + h - 1), (255, 200, 0), 3)
    if quad is not None:
        pts = (quad + np.array([ox, oy], dtype=np.float32)).astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(p1, [pts], True, (0, 255, 0), 4)
    p2 = base.copy()
    sub = p2[oy:oy + h, ox:ox + w]
    sub[lb_grown] = (0.5 * sub[lb_grown] + 0.5 * np.array([0, 0, 255])).astype(np.uint8)
    p3 = cv2.cvtColor(np.clip(g_film, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    p4 = cv2.cvtColor(to_uint8(digital), cv2.COLOR_GRAY2BGR)
    panels = [_fit_height(p, height) for p in (p1, p2, p3, p4)]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    cv2.imwrite(path, np.hstack(panels), [int(cv2.IMWRITE_JPEG_QUALITY), 85])


# --------------------------------------------------------------------------
# Helpers for the app
# --------------------------------------------------------------------------
def make_preview(src_png: str, dst_jpg: str, max_side: int = 1280, quality: int = 90) -> Tuple[int, int]:
    """8-bit JPEG preview for the UI / PDF (a 16-bit 12-megapixel PNG is too heavy to show on a Pi).
    Returns the (width, height) of the ORIGINAL image."""
    raw = cv2.imread(str(src_png), cv2.IMREAD_UNCHANGED)
    if raw is None:
        raise ValueError("cannot read image: %s" % src_png)
    if raw.ndim == 3:
        raw = cv2.cvtColor(raw, cv2.COLOR_BGRA2GRAY if raw.shape[2] == 4 else cv2.COLOR_BGR2GRAY)
    h, w = raw.shape
    img = to_uint8(raw)
    s = max_side / float(max(h, w))
    if s < 1.0:
        img = cv2.resize(img, (max(1, int(round(w * s))), max(1, int(round(h * s)))), interpolation=cv2.INTER_AREA)
    os.makedirs(os.path.dirname(dst_jpg) or ".", exist_ok=True)
    cv2.imwrite(dst_jpg, img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return w, h
