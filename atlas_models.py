"""
ATLAS-BC inference: the trained 15-network ensemble (ResNet50, DenseNet121, InceptionV3 x 5 folds).

Everything here is the training notebook's own code, ported for inference only:

* ``MammoNet`` and its backbones   -> notebook Cell 3  (names of all layers are unchanged, so the checkpoints load
  strictly: a wrong or damaged file raises an error instead of silently giving wrong numbers)
* input preparation                -> notebook Cell 2  ``prepare_batch(train=False)``: /255, (x - 0.449) / 0.226 and
  the "tissue" map ``avg_pool(x > 0.02, 32) > 0.15``
* per-architecture average over folds, then the weighted average over the three architectures
  (``combine: "wa"``, weights from the ensemble's ``final_config.json``) -> notebook Cells 4 and 11
* the decision ("five" in the config): the most probable of the five BI-RADS classes per breast

Do NOT "improve" the maths: the networks were trained on exactly this.

Files expected (see ``MODELS_DIR`` below)::

    models/ensemble_config.json            copy of v3_ensemble/final_config.json
    models/resnet50_in/fold0_best.pth ...  fold4_best.pth
    models/densenet121_in/fold0_best.pth ...
    models/inception_v3_in/fold0_best.pth ...

Settings (environment variables)::

    ATLAS_MODELS_DIR       folder with the files above                      default: <this folder>/models
    ATLAS_TORCH_THREADS    CPU threads PyTorch may use                      default: all cores
    ATLAS_VIEW_CHUNK       views pushed through a network at once (1..4)    default: 4. Lower = less RAM, same result.
    ATLAS_KEEP_MODELS      1 = keep all 15 networks in RAM (about 1.2 GB; fast)   default: 1
                           0 = load each network just before it is used and free it afterwards (slow, small RAM)
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from typing import Callable, Dict, List, Optional

import numpy as np

# --------------------------------------------------------------------------
# Constants shared with the training notebook (Cell 1)
# --------------------------------------------------------------------------
IMG_H, IMG_W = 1280, 800
STRIDE = 32
MEAN, STD = 0.449, 0.226
FEAT_DIM = 512
TOP_K = 8
N_CATS = 10                       # the finding-type head (unused at inference, but part of the checkpoint)
SLOTS = [("L", "CC"), ("L", "MLO"), ("R", "CC"), ("R", "MLO")]
CLASS_NAMES = ["BI-RADS 1", "BI-RADS 2", "BI-RADS 3", "BI-RADS 4", "BI-RADS 5"]

MODELS_DIR = os.environ.get("ATLAS_MODELS_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
CONFIG_NAME = "ensemble_config.json"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


class ModelsUnavailable(RuntimeError):
    """The PyTorch packages or the model files are missing (the message says which)."""


def _import_torch():
    try:
        import torch
        import torch.nn as nn
        import torch.nn.functional as F
        from torchvision import models
    except Exception as exc:  # ImportError, or a broken install (e.g. wrong CPU architecture)
        raise ModelsUnavailable(
            f"PyTorch / torchvision cannot be imported ({exc}). Install them on the machine that runs the "
            "backend (see deploy/README.md, step 3b).") from exc
    return torch, nn, F, models


# --------------------------------------------------------------------------
# The network (notebook Cell 3), built lazily so that importing this module never needs PyTorch
# --------------------------------------------------------------------------
_NET_CLASSES = {}


def _net_classes():
    """Returns (MammoNet, build_backbone). Defined inside a function so that `import atlas_models` works on a machine
    without PyTorch (the backend then reports a clear error only when an analysis is requested)."""
    if _NET_CLASSES:
        return _NET_CLASSES["MammoNet"], _NET_CLASSES["build_backbone"]
    torch, nn, F, models = _import_torch()

    def _adapt_first_conv(module):
        """3-channel stem -> 1-channel (weights summed over RGB): mammograms are grayscale."""
        for name, m in module.named_modules():
            if isinstance(m, nn.Conv2d) and m.in_channels == 3:
                new = nn.Conv2d(1, m.out_channels, m.kernel_size, m.stride, m.padding, bias=m.bias is not None)
                with torch.no_grad():
                    new.weight.copy_(m.weight.sum(1, keepdim=True))
                    if m.bias is not None:
                        new.bias.copy_(m.bias)
                parent, parts = module, name.split(".")
                for p in parts[:-1]:
                    parent = getattr(parent, p)
                setattr(parent, parts[-1], new)
                return
        raise RuntimeError("no 3-channel conv found")

    class Affine(nn.Module):
        def __init__(self, a, b):
            super().__init__()
            self.a, self.b = a, b

        def forward(self, x):
            return x * self.a + self.b

    class StagedBackbone(nn.Module):
        """Backbone as a list of stages (inference only: no freezing, no checkpointing)."""
        def __init__(self, stages, out_ch):
            super().__init__()
            self.stages, self.out_ch = nn.ModuleList(stages), out_ch

        def forward(self, x):
            for s in self.stages:
                x = s(x)
            return x

    def build_backbone(arch):
        """The three ImageNet backbones of the final ensemble, WITHOUT downloading pretrained weights (the
        checkpoint holds every weight)."""
        if arch == "resnet50_in":
            m = models.resnet50(weights=None)
            _adapt_first_conv(m)
            return StagedBackbone([nn.Sequential(m.conv1, m.bn1, m.relu, m.maxpool), m.layer1, m.layer2, m.layer3,
                                   m.layer4], 2048)
        if arch == "densenet121_in":
            m = models.densenet121(weights=None)
            _adapt_first_conv(m)
            ch = list(m.features.children())        # conv0 norm0 relu0 pool0 db1 tr1 db2 tr2 db3 tr3 db4 norm5
            return StagedBackbone([nn.Sequential(*ch[:4]), nn.Sequential(ch[4], ch[5]), nn.Sequential(ch[6], ch[7]),
                                   nn.Sequential(ch[8], ch[9]), nn.Sequential(ch[10], ch[11], nn.ReLU())], 1024)
        if arch == "inception_v3_in":
            m = models.inception_v3(weights=None, aux_logits=False, transform_input=False, init_weights=False)
            _adapt_first_conv(m)
            # torchvision's ImageNet weights expect inputs in [-1, 1]
            stem = [Affine(STD / 0.5, (MEAN - 0.5) / 0.5), m.Conv2d_1a_3x3, m.Conv2d_2a_3x3, m.Conv2d_2b_3x3, m.maxpool1]
            return StagedBackbone([nn.Sequential(*stem), nn.Sequential(m.Conv2d_3b_1x1, m.Conv2d_4a_3x3, m.maxpool2),
                                   nn.Sequential(m.Mixed_5b, m.Mixed_5c, m.Mixed_5d),
                                   nn.Sequential(m.Mixed_6a, m.Mixed_6b, m.Mixed_6c, m.Mixed_6d, m.Mixed_6e),
                                   nn.Sequential(m.Mixed_7a, m.Mixed_7b, m.Mixed_7c)], 2048)
        raise ValueError(f"unknown architecture {arch!r} (this build knows resnet50_in, densenet121_in, inception_v3_in)")

    class MammoNet(nn.Module):
        """4 views (L-CC, L-MLO, R-CC, R-MLO) -> shared CNN -> per-view location map -> attention + top-k pooling ->
        per-breast vector -> compared with the OTHER breast -> 5-class (nominal + ordinal CORAL) + density head."""
        def __init__(self, arch, d=FEAT_DIM, top_k=TOP_K, n_cats=N_CATS, dropout=0.3):
            super().__init__()
            self.top_k = top_k
            self.backbone = build_backbone(arch)
            self.proj = nn.Sequential(nn.Conv2d(self.backbone.out_ch, d, 1, bias=False), nn.GroupNorm(32, d), nn.GELU())
            self.att_v, self.att_u, self.att_w = nn.Conv2d(d, 256, 1), nn.Conv2d(d, 256, 1), nn.Conv2d(256, 1, 1)
            self.lesion = nn.Conv2d(d, 1, 1)
            e = 3 * d
            self.cat_head = nn.Linear(e, n_cats)
            self.breast_proj = nn.Sequential(nn.Linear(2 * e, d), nn.LayerNorm(d), nn.GELU(), nn.Dropout(dropout))
            self.fuse = nn.Sequential(nn.Linear(3 * d + 6, 256), nn.LayerNorm(256), nn.GELU(), nn.Dropout(dropout))
            self.nominal = nn.Linear(256, 5)
            self.ord_fc = nn.Linear(256, 1, bias=False)
            self.ord_bias = nn.Parameter(torch.tensor([0.5, -0.5, -1.5, -2.5]))
            self.density = nn.Linear(256, 4)

        def forward(self, x, fg, view_chunk=4):
            """Same maths as the notebook's forward.  `view_chunk` only changes how many of the 4N images go through
            the CNN at a time (BatchNorm is frozen, so the result is identical); smaller = less memory."""
            N = x.shape[0]
            B = N // 4
            view_chunk = max(1, int(view_chunk))
            f = torch.cat([self.proj(self.backbone(x[i:i + view_chunk])) for i in range(0, N, view_chunk)])
            _, d, h, w = f.shape
            if tuple(fg.shape[-2:]) != (h, w):                                # e.g. InceptionV3 has a 38x23 grid
                fg = F.interpolate(fg.unsqueeze(1).float(), size=(h, w), mode="nearest").squeeze(1) > 0.5
            fl = f.flatten(2)                                                 # (N, d, L)
            fgf = fg.flatten(1)
            valid = fgf | ~fgf.any(1, keepdim=True)                           # blank image -> use every location
            z = self.lesion(f).flatten(1).float()                             # (N, L)
            a = self.att_w(torch.tanh(self.att_v(f)) * torch.sigmoid(self.att_u(f))).flatten(1).float()
            z_m, a_m = z.masked_fill(~valid, -1e4), a.masked_fill(~valid, -1e4)

            f_att = (fl * torch.softmax(a_m, 1).to(fl.dtype).unsqueeze(1)).sum(-1)
            kk = min(self.top_k, fl.shape[-1])
            tv, ti = z_m.topk(kk, dim=1)
            f_top = (fl.gather(2, ti.unsqueeze(1).expand(-1, d, -1)) * torch.softmax(tv, 1).to(fl.dtype).unsqueeze(1)).sum(-1)
            vm = valid.to(fl.dtype)
            f_mean = (fl * vm.unsqueeze(1)).sum(-1) / vm.sum(1, keepdim=True).clamp(min=1)
            e = torch.cat([f_att, f_top, f_top - f_mean], dim=1)              # (N, 3d)
            peak = tv[:, :min(4, kk)].mean(1)                                 # strongest lesion evidence in the view

            bv = self.breast_proj(e.view(B, 2, 2 * e.shape[1]))               # (B, side, d)  [CC | MLO] of each breast
            pk = peak.view(B, 2, 2)
            bc, pkc = bv.flip(1), pk.flip(1)                                  # the OTHER breast
            hid = self.fuse(torch.cat([bv, bc, bv - bc, pk.to(bv.dtype), pkc.to(bv.dtype), (pk - pkc).to(bv.dtype)], dim=-1))
            return {"nom": self.nominal(hid).float(), "ord": (self.ord_fc(hid) + self.ord_bias).float()}

        @staticmethod
        def probs(out):
            """Fused class probabilities (B, 2, 5): half nominal softmax, half ordinal (CORAL)."""
            pn, c = torch.softmax(out["nom"], -1), torch.sigmoid(out["ord"])
            po = torch.stack([1 - c[..., 0], (c[..., 0] - c[..., 1]).clamp(min=0), (c[..., 1] - c[..., 2]).clamp(min=0),
                              (c[..., 2] - c[..., 3]).clamp(min=0), c[..., 3]], dim=-1)
            po = po / (po.sum(-1, keepdim=True) + 1e-8)
            return 0.5 * pn + 0.5 * po

    _NET_CLASSES.update({"MammoNet": MammoNet, "build_backbone": build_backbone})
    return MammoNet, build_backbone


# --------------------------------------------------------------------------
# Input preparation (notebook Cell 2, prepare_batch with train=False)
# --------------------------------------------------------------------------
def prepare_input(canvases: List[np.ndarray]):
    """canvases: four uint8 arrays (1280, 800) in the order L-CC, L-MLO, R-CC, R-MLO (the output of
    atlas_preprocess.process_image + fill_slots).  Returns (x, fg) for MammoNet."""
    torch, _nn, F, _models = _import_torch()
    arr = np.stack([np.ascontiguousarray(c, dtype=np.uint8) for c in canvases])
    if arr.shape != (4, IMG_H, IMG_W):
        raise ValueError(f"the model needs 4 images of {IMG_H}x{IMG_W}, got {tuple(arr.shape)}")
    x = torch.from_numpy(arr).reshape(4, 1, IMG_H, IMG_W).float().div_(255.0)
    fg = (F.avg_pool2d((x > 0.02).float(), STRIDE) > 0.15).squeeze(1)         # (4, h, w) tissue locations
    xin = ((x - MEAN) / STD).contiguous(memory_format=torch.channels_last)
    return xin, fg


# --------------------------------------------------------------------------
# Combining the networks (notebook Cell 4)
# --------------------------------------------------------------------------
def wa_aggregate(P_list, w):
    """Weighted average of one (.., 5) probability table per architecture."""
    w = np.clip(np.asarray(w, float), 0, None)
    return np.tensordot(w / w.sum(), np.stack(P_list), axes=1)


def combine_probs(P_list, mode: str, params: Optional[dict] = None):
    if len(P_list) == 1:
        return P_list[0]
    if mode == "mean":
        return np.mean(P_list, axis=0)
    if mode == "wa":
        return wa_aggregate(P_list, params["w"])
    raise ValueError(f"combination {mode!r} is not part of the deployed ensemble (config says 'wa' or 'mean')")


def decide_five(P5: np.ndarray) -> int:
    """decide = "five": the most probable of the five BI-RADS classes (the 5-class scheme has all offsets 0)."""
    return int(np.argmax(P5))


# --------------------------------------------------------------------------
# The ensemble
# --------------------------------------------------------------------------
class Ensemble:
    def __init__(self, models_dir: Optional[str] = None):
        self.models_dir = models_dir or MODELS_DIR
        self.cfg: dict = {}
        self.members: List[dict] = []          # [{"arch": str, "files": [path, ...]}]
        self._nets: Dict[str, object] = {}     # path -> network (when ATLAS_KEEP_MODELS=1)
        self._lock = threading.Lock()          # one analysis at a time: the CPU is the bottleneck anyway
        self.keep = _env_int("ATLAS_KEEP_MODELS", 1) != 0
        self.view_chunk = max(1, min(4, _env_int("ATLAS_VIEW_CHUNK", 4)))
        self.loaded = False
        self.error: Optional[str] = None
        self.last_seconds: Optional[float] = None

    # ----- files -----
    def check_files(self) -> None:
        """Raises ModelsUnavailable when the config or any of the 15 checkpoints is missing."""
        cfg_path = os.path.join(self.models_dir, CONFIG_NAME)
        if not os.path.isfile(cfg_path):
            raise ModelsUnavailable(f"{cfg_path} not found. Copy the model folder to the machine "
                                    f"(or set ATLAS_MODELS_DIR); see deploy/README.md, step 3b.")
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if (cfg.get("img_h"), cfg.get("img_w")) != (IMG_H, IMG_W):
            raise ModelsUnavailable(f"{CONFIG_NAME} was trained for {cfg.get('img_h')}x{cfg.get('img_w')} inputs, "
                                    f"this backend produces {IMG_H}x{IMG_W}")
        members, missing = [], []
        for mem in cfg["members"]:
            files = [os.path.join(self.models_dir, mem["arch"], f"fold{k}_best.pth") for k in mem["folds"]]
            missing += [p for p in files if not os.path.isfile(p)]
            members.append({"arch": mem["arch"], "files": files})
        if missing:
            shown = ", ".join(os.path.relpath(p, self.models_dir) for p in missing[:4])
            raise ModelsUnavailable(f"{len(missing)} model file(s) missing in {self.models_dir}: {shown}"
                                    f"{' ...' if len(missing) > 4 else ''}")
        self.cfg, self.members = cfg, members

    @property
    def n_networks(self) -> int:
        return sum(len(m["files"]) for m in self.members)

    def _load_net(self, arch: str, path: str):
        torch, _nn, _F, _models = _import_torch()
        MammoNet, _ = _net_classes()
        try:
            ck = torch.load(path, map_location="cpu", weights_only=True)
        except Exception:               # a checkpoint that stores more than plain tensors (our own files only)
            ck = torch.load(path, map_location="cpu", weights_only=False)
        if ck.get("arch") not in (None, arch):
            raise ModelsUnavailable(f"{path} holds a {ck.get('arch')} network, expected {arch}")
        net = MammoNet(arch)
        net.load_state_dict(ck["model"])            # strict: any mismatch is an error
        return net.eval().to(memory_format=torch.channels_last)

    def _get_net(self, arch: str, path: str):
        if path in self._nets:
            return self._nets[path]
        net = self._load_net(arch, path)
        if self.keep:
            self._nets[path] = net
        return net

    def load(self, progress: Optional[Callable[[int, int], None]] = None) -> None:
        """Checks the files and (with ATLAS_KEEP_MODELS=1) loads all networks.  Safe to call more than once."""
        with self._lock:
            if self.loaded:
                return
            try:
                torch, _nn, _F, _models = _import_torch()
                n_threads = _env_int("ATLAS_TORCH_THREADS", 0) or (os.cpu_count() or 1)
                torch.set_num_threads(max(1, n_threads))
                self.check_files()
                if self.keep:
                    done = 0
                    for mem in self.members:
                        for path in mem["files"]:
                            self._get_net(mem["arch"], path)
                            done += 1
                            if progress:
                                progress(done, self.n_networks)
                self.loaded, self.error = True, None
            except Exception as exc:
                self.error = str(exc)
                raise

    # ----- prediction -----
    def predict(self, slot_canvases: Dict[tuple, np.ndarray], sides) -> Dict[str, List[float]]:
        """slot_canvases: {('L','CC'): uint8[1280, 800], ...}, always all four (see atlas_preprocess.fill_slots).
        sides: the sides that have at least one real view.  Returns {'L': [P(B1)..P(B5)], 'R': [...]}."""
        torch, _nn, _F, _models = _import_torch()
        MammoNet, _ = _net_classes()
        if not self.loaded:
            self.load()
        t0 = time.time()
        with self._lock, torch.inference_mode():
            x, fg = prepare_input([slot_canvases[s] for s in SLOTS])
            per_member = []
            for mem in self.members:
                fold_probs = []
                for path in mem["files"]:
                    net = self._get_net(mem["arch"], path)
                    out = net(x, fg, view_chunk=self.view_chunk)
                    fold_probs.append(MammoNet.probs(out).float().cpu().numpy()[0])      # (2, 5)
                    if not self.keep:
                        del net
                per_member.append(np.mean(fold_probs, axis=0))                           # mean over the 5 folds
            P = combine_probs(per_member, self.cfg["combine"], self.cfg.get("calibration"))   # (2, 5)
        self.last_seconds = time.time() - t0
        P = np.asarray(P, np.float64)
        P = P / P.sum(-1, keepdims=True)
        return {side: [float(v) for v in P[{"L": 0, "R": 1}[side]]] for side in sides}

    def info(self) -> dict:
        return {"loaded": self.loaded, "error": self.error, "networks": self.n_networks or None,
                "combine": self.cfg.get("combine"), "decide": self.cfg.get("decide"),
                "last_analysis_seconds": None if self.last_seconds is None else round(self.last_seconds, 1)}


_ENSEMBLE: Optional[Ensemble] = None
_ENSEMBLE_LOCK = threading.Lock()


def get_ensemble() -> Ensemble:
    global _ENSEMBLE
    with _ENSEMBLE_LOCK:
        if _ENSEMBLE is None:
            _ENSEMBLE = Ensemble()
        return _ENSEMBLE


def run_ensemble(slot_canvases, sides):
    """The function app.py calls (`run_models`): see Ensemble.predict."""
    return get_ensemble().predict(slot_canvases, sides)


def preload_in_background() -> threading.Thread:
    """Loads the networks while the operator is still capturing views, so the first analysis starts at once.
    Errors are kept in ensemble.error (shown by /health) and raised again by the first analysis."""
    def work():
        try:
            get_ensemble().load()
        except Exception:
            pass
    t = threading.Thread(target=work, name="atlas-preload", daemon=True)
    t.start()
    return t
