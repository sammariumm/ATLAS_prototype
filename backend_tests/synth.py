"""Synthetic test images: a fake digital mammogram and a fake camera photo of it on a lightbox."""
import cv2
import numpy as np


def make_digital(h=1400, w=1000, seed=0, side="L"):
    """uint8 'digital mammogram': background exactly 0, chest wall on the LEFT edge (RIGHT for side='R')."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    a, b = 0.88 * w, 0.40 * h
    d2 = (xx / a) ** 2 + ((yy - 0.5 * h) / b) ** 2
    inside = d2 <= 1.0
    noise = rng.normal(0, 1, (h, w)).astype(np.float32)
    tex = cv2.GaussianBlur(noise, (0, 0), 7)
    tex /= tex.std() + 1e-6
    tex2 = cv2.GaussianBlur(noise, (0, 0), 2)
    tex2 /= tex2.std() + 1e-6
    img = 55 + 55 * np.clip(1.0 - d2, 0, 1) + 22 * tex + 6 * tex2
    pect = (xx + 0.45 * yy) < 0.22 * w                      # bright pectoral muscle, top left
    img = np.where(pect & inside, img + 55, img)
    img = np.where(inside & (d2 > 0.93), img + 18, img)      # skin line
    img = np.where(inside, np.clip(img, 12, 235), 0)
    ly0, ly1, lx0, lx1 = int(0.03 * h), int(0.10 * h), int(0.62 * w), int(0.97 * w)   # ID label patch
    patch = np.full((ly1 - ly0, lx1 - lx0), 215, np.float32)
    patch[3::9, :] = 40
    img[ly0:ly1, lx0:lx1] = patch
    out = img.astype(np.uint8)
    if side == "R":
        out = np.ascontiguousarray(out[:, ::-1])
    return out


def make_film_photo(digital, frame_hw=(1640, 1232), angle=2.5, fill=0.86, lightbox=240.0, film_black=6.0,
                    tissue_max=0.62, margin_px=0, margin_level=0.80, glare=0.0, vignette=0.10, noise=2.0,
                    blur=1.2, seed=1, enclosure=False, offset=(0, 0)):
    """BGR uint8 photo of `digital` printed on film and laid on a lightbox (optionally slightly rotated)."""
    rng = np.random.default_rng(seed)
    H, W = frame_hw
    film = film_black + (digital.astype(np.float32) / 255.0) * (tissue_max * lightbox - film_black)
    film = np.where(digital > 0, film, film_black).astype(np.float32)
    if margin_px > 0:   # clear (unexposed) film border
        film = cv2.copyMakeBorder(film, margin_px, margin_px, margin_px, margin_px, cv2.BORDER_CONSTANT,
                                  value=margin_level * lightbox)
    fh, fw = film.shape
    s = min(fill * H / fh, fill * W / fw)
    cx, cy = W / 2 + offset[0], H / 2 + offset[1]
    M = cv2.getRotationMatrix2D((fw / 2, fh / 2), angle, s)
    M[0, 2] += cx - fw / 2
    M[1, 2] += cy - fh / 2
    placed = cv2.warpAffine(film, M, (W, H), flags=cv2.INTER_LINEAR, borderValue=0)
    cover = cv2.warpAffine(np.ones_like(film), M, (W, H), flags=cv2.INTER_LINEAR, borderValue=0)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r2 = ((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2
    vig = 1.0 - vignette * r2 / 2.0
    lb = lightbox * vig
    frame = lb * (1.0 - cover) + placed * vig * cover
    if enclosure:   # light only comes through a window; outside it is a dark enclosure
        win = np.zeros((H, W), np.float32)
        wx, wy = int(0.05 * W), int(0.04 * H)
        win[wy:H - wy, wx:W - wx] = 1.0
        win = cv2.GaussianBlur(win, (0, 0), 2.0)
        frame = frame * win + 8.0 * (1.0 - win)
        lb = lb * win
    if glare > 0:       # veiling glare: light from the bright area leaks into the dark film
        bright = (lb * (1.0 - cover)) / lightbox
        frame = frame + glare * cv2.GaussianBlur(bright, (0, 0), 40) * lightbox
    frame = cv2.GaussianBlur(frame, (0, 0), blur) if blur > 0 else frame
    frame = frame + rng.normal(0, noise, frame.shape)
    g = np.clip(frame, 0, 255).astype(np.uint8)
    return cv2.merge([g, g, g])
