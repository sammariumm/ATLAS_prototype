"""
Softcopy -> PNG conversion for ATLAS-BC.

Rules (as requested):
  * DICOM  -> converted to PNG first.
  * PNG    -> stays a PNG: the file is copied byte for byte, never re-encoded.
  * anything else (JPEG, BMP, TIFF, GIF, WebP, JPEG 2000, ...) -> converted to PNG.

The format is recognised from the file's content (magic bytes), not from its extension, so a DICOM that
was renamed ``.png`` (or a PNG named ``.dcm``) is still handled correctly.

DICOM details
  * pixel data is decoded with pydicom (compressed transfer syntaxes need the pylibjpeg / gdcm plugins)
  * the modality LUT (RescaleSlope / RescaleIntercept) is applied
  * MONOCHROME1 is inverted so the background is black, like MONOCHROME2
  * multi-frame files (tomosynthesis) use the middle frame, with a warning
  * output bit depth: 16-bit by default (lossless; ``process_image`` copes with 8 or 16 bit).
    Environment: ATLAS_DICOM_PNG_BITS=8|16, ATLAS_DICOM_VOI=1 to apply the VOI LUT / window from the header.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from typing import List, Optional

import cv2
import numpy as np


class ConversionError(Exception):
    """The file cannot be turned into a PNG; the message is meant for the operator."""


@dataclass
class ConversionResult:
    png_path: str
    source_format: str          # 'dicom', 'png', 'jpeg', 'tiff', ...
    converted: bool             # False when the file already was a PNG and was kept as it is
    bit_depth: int              # bits per channel of the PNG written
    width: int
    height: int
    warnings: List[str] = field(default_factory=list)


_DICOM_EXT = {".dcm", ".dicom", ".dic", ".ima"}


def sniff_format(path: str) -> str:
    """Recognise the file type from its first bytes."""
    with open(path, "rb") as f:
        head = f.read(132)
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if len(head) >= 132 and head[128:132] == b"DICM":
        return "dicom"
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if head[:2] == b"BM":
        return "bmp"
    if head[:4] in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"):
        return "tiff"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[:12] == b"\x00\x00\x00\x0cjP  \r\n\x87\n" or head[:4] == b"\xff\x4f\xff\x51":
        return "jpeg2000"
    if os.path.splitext(path)[1].lower() in _DICOM_EXT:
        return "dicom"  # DICOM without the 128-byte preamble
    return "unknown"


def _env_bits(default: int = 16) -> int:
    v = os.environ.get("ATLAS_DICOM_PNG_BITS", "").strip()
    return 8 if v == "8" else 16 if v == "16" else default


def _env_flag(name: str, default: bool = False) -> bool:
    v = os.environ.get(name, "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return default


def _unique_png_path(out_dir: str, stem: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, stem + ".png")
    n = 1
    while os.path.exists(path):
        path = os.path.join(out_dir, "%s_%d.png" % (stem, n))
        n += 1
    return path


def _scale_to_bits(a: np.ndarray, bits: int) -> np.ndarray:
    """Scale linearly so the brightest pixel becomes 255 / 65535 (a 12-bit DICOM would otherwise look almost black in
    a 16-bit PNG).  Zero stays zero: the background must stay black."""
    top = 65535.0 if bits == 16 else 255.0
    out_t = np.uint16 if bits == 16 else np.uint8
    if bits == 8 and a.dtype == np.uint8:
        return a  # already 8-bit: keep as it is
    a = a.astype(np.float64)
    lo = float(a.min())
    if lo < 0:
        a = a - lo
    hi = float(a.max())
    if hi <= 0:
        return np.zeros(a.shape, out_t)
    return np.rint(a * (top / hi)).astype(out_t)


# ---------------------------------------------------------------- DICOM ---
def _pixel_utils():
    """pydicom moved these helpers in version 3; support both."""
    mod = None
    try:
        import pydicom.pixels as mod  # type: ignore  # pydicom >= 3.0
    except Exception:
        try:
            import pydicom.pixel_data_handlers.util as mod  # type: ignore  # pydicom 2.x
        except Exception:
            mod = None
    return (getattr(mod, "apply_modality_lut", None), getattr(mod, "apply_voi_lut", None))


def dicom_to_array(path: str, bits: Optional[int] = None, apply_voi: Optional[bool] = None):
    """DICOM file -> (uint8/uint16 grey array, warnings, bit depth)."""
    bits = bits or _env_bits()
    apply_voi = _env_flag("ATLAS_DICOM_VOI", False) if apply_voi is None else apply_voi
    warnings: List[str] = []
    try:
        import pydicom
    except ImportError as exc:
        raise ConversionError("DICOM files need the 'pydicom' package (pip install pydicom).") from exc
    try:
        ds = pydicom.dcmread(path, force=True)
    except Exception as exc:
        raise ConversionError("Not a readable DICOM file: %s" % exc) from exc
    if "PixelData" not in ds:
        raise ConversionError("This DICOM file contains no image (no pixel data); it may be a report or a "
                              "presentation state.")
    try:
        arr = ds.pixel_array
    except Exception as exc:
        ts = getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", None)
        raise ConversionError(
            "Could not decode the DICOM image (transfer syntax %s). If it is JPEG / JPEG-2000 compressed, install "
            "the decoders: pip install pylibjpeg pylibjpeg-libjpeg pylibjpeg-openjpeg  (%s)" % (ts, exc)) from exc

    samples = int(getattr(ds, "SamplesPerPixel", 1) or 1)
    frames = int(getattr(ds, "NumberOfFrames", 1) or 1)
    if frames > 1:
        warnings.append("Multi-frame DICOM (%d frames): the middle frame was used." % frames)
        arr = arr[frames // 2]
    if samples == 3 and arr.ndim == 3:
        arr = np.rint(arr.astype(np.float64) @ np.array([0.299, 0.587, 0.114])).astype(np.float64)
    arr = np.squeeze(arr)
    if arr.ndim != 2:
        raise ConversionError("Unsupported DICOM image layout (shape %s)." % (arr.shape,))

    apply_modality, apply_voi_lut = _pixel_utils()
    if apply_modality is not None:
        try:
            arr = apply_modality(arr, ds)
        except Exception as exc:
            warnings.append("Could not apply the rescale slope/intercept (%s); the stored values were used." % exc)
    else:
        slope = float(getattr(ds, "RescaleSlope", 1) or 1)
        icpt = float(getattr(ds, "RescaleIntercept", 0) or 0)
        if slope != 1.0 or icpt != 0.0:
            arr = arr.astype(np.float64) * slope + icpt
    if apply_voi and apply_voi_lut is not None:
        try:
            arr = apply_voi_lut(arr, ds)
        except Exception as exc:
            warnings.append("Could not apply the VOI LUT (%s); the full range was used." % exc)

    arr = np.asarray(arr)
    if str(getattr(ds, "PhotometricInterpretation", "MONOCHROME2")).upper() == "MONOCHROME1":
        arr = arr.max() - arr  # MONOCHROME1: low value = white; flip so the air/background becomes 0

    return _scale_to_bits(arr, bits), warnings, bits


# --------------------------------------------------------- other images ---
def _read_other(path: str):
    """Any non-DICOM image -> numpy array (cv2 first, Pillow as a fallback)."""
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is not None:
        return img
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as im:
            im.seek(0)
            mode = im.mode
            if mode in ("I;16", "I;16L", "I;16B", "I;16N"):
                return np.array(im, dtype=np.uint16)
            if mode in ("I", "F"):
                return np.array(im)
            if mode in ("L", "RGB", "RGBA"):
                a = np.array(im)
            elif mode in ("LA", "P", "PA", "1", "CMYK", "YCbCr", "LAB", "HSV"):
                a = np.array(im.convert("RGBA" if "A" in mode or (mode == "P" and "transparency" in im.info) else "RGB"))
            else:
                a = np.array(im.convert("RGB"))
            if a.ndim == 3:  # RGB(A) -> BGR(A) for OpenCV
                a = a[:, :, [2, 1, 0] + ([3] if a.shape[2] == 4 else [])]
            return a
    except Exception:
        return None


def _normalise_dtype(img: np.ndarray) -> np.ndarray:
    if img.dtype in (np.uint8, np.uint16):
        return img
    a = img.astype(np.float64)
    a = a - min(0.0, float(a.min()))
    hi = float(a.max())
    return np.rint(a * (65535.0 / hi)).astype(np.uint16) if hi > 0 else np.zeros(img.shape, np.uint16)


# ------------------------------------------------------------------ API ---
def convert_to_png(src: str, out_dir: str, stem: Optional[str] = None,
                   dicom_bits: Optional[int] = None, dicom_voi: Optional[bool] = None) -> ConversionResult:
    """Turn any supported softcopy into a PNG inside ``out_dir`` and describe what was done."""
    if not os.path.isfile(src):
        raise ConversionError("File not found: %s" % os.path.basename(src))
    if os.path.getsize(src) == 0:
        raise ConversionError("The file is empty: %s" % os.path.basename(src))
    stem = stem or os.path.splitext(os.path.basename(src))[0]
    fmt = sniff_format(src)

    if fmt == "png":
        probe = cv2.imread(src, cv2.IMREAD_UNCHANGED)
        if probe is None:
            raise ConversionError("The PNG file is damaged or uses an unsupported variant.")
        dst = _unique_png_path(out_dir, stem)
        shutil.copyfile(src, dst)  # already a PNG: keep it exactly as it is
        return ConversionResult(dst, "png", False, 16 if probe.dtype == np.uint16 else 8,
                                int(probe.shape[1]), int(probe.shape[0]), [])

    if fmt == "dicom":
        arr, warnings, bits = dicom_to_array(src, dicom_bits, dicom_voi)
        dst = _unique_png_path(out_dir, stem)
        if not cv2.imwrite(dst, arr, [int(cv2.IMWRITE_PNG_COMPRESSION), 3]):
            raise ConversionError("Could not write the PNG file.")
        return ConversionResult(dst, "dicom", True, bits, int(arr.shape[1]), int(arr.shape[0]), warnings)

    img = _read_other(src)
    if img is None:
        raise ConversionError("Unsupported or damaged file (%s). Supported: DICOM, PNG, JPEG, BMP, TIFF, GIF, WebP."
                              % os.path.basename(src))
    img = _normalise_dtype(img)
    dst = _unique_png_path(out_dir, stem)
    if not cv2.imwrite(dst, img, [int(cv2.IMWRITE_PNG_COMPRESSION), 3]):
        raise ConversionError("Could not write the PNG file.")
    return ConversionResult(dst, fmt if fmt != "unknown" else "image", True,
                            16 if img.dtype == np.uint16 else 8, int(img.shape[1]), int(img.shape[0]), [])
