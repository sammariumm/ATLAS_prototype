#!/usr/bin/env python3
"""
ATLAS-BC evaluation: runs test mammograms through the SAME code the device uses and scores the results.

It answers two questions:
  1. Does the device reproduce our tested model?   (optional --compare with the notebook's own predictions)
  2. How good are the predictions?                 (accuracy, per-class recall, confusion matrix, AUC, calibration)

The pipeline is the backend's own, step by step (app.py /import and /analyze):
  file -> atlas_convert.convert_to_png -> atlas_preprocess.process_image -> fill_slots -> atlas_models.run_ensemble
so a mismatch here means a mismatch on the device.  Pure numpy: no scikit-learn needed on the Pi.

Put this file next to app.py.  Three ways to run it:

  A) VinDr-Mammo test split (picks a class-balanced sample; BI-RADS 4 and 5 are rare, so a random sample misses them):
       python3 atlas_evaluate.py --vindr breast-level_annotations.csv --images /path/to/vindr/images --per-class 4

  B) Your own list of cases, a CSV with these columns (leave a cell empty if that view is missing):
       study_id,L_CC,L_MLO,R_CC,R_MLO,birads_L,birads_R
       case01,/media/usb/c1_lcc.dcm,/media/usb/c1_lmlo.dcm,/media/usb/c1_rcc.dcm,/media/usb/c1_rmlo.dcm,1,4
       python3 atlas_evaluate.py --cases my_cases.csv

  C) Metrics only, from a predictions CSV made earlier (by A/B, or exported from the notebook):
       python3 atlas_evaluate.py --predictions atlas_eval_predictions.csv

  Add  --compare notebook_predictions.csv  to A/B/C to check the device against the notebook.  That file needs the
  columns study_id,side,p1,p2,p3,p4,p5 (side = L or R).

Writes atlas_eval_predictions.csv (one row per breast) and atlas_eval_report.txt, and prints the report.
Stop the backend first (sudo systemctl stop atlas-backend.service): the 15 networks need the RAM.
"""
from __future__ import annotations

import argparse
import csv
import os
import random
import sys
import tempfile
import time
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

K = 5
NAMES = [f"B{i}" for i in range(1, K + 1)]


# --------------------------------------------------------------------------
# Reading the cases
# --------------------------------------------------------------------------
def _birads(v):
    """'BI-RADS 4', '4', 4 -> 4;  empty / unknown -> None."""
    s = str(v or "").strip().upper().replace("BI-RADS", "").strip()
    try:
        k = int(float(s))
    except ValueError:
        return None
    return k if 1 <= k <= K else None


def _find_image(root, study_id, image_id):
    for ext in (".dicom", ".dcm", ".png", ".jpg", ".jpeg", ".tif", ".tiff"):
        for p in (os.path.join(root, study_id, image_id + ext), os.path.join(root, image_id + ext)):
            if os.path.isfile(p):
                return p
    return None


def cases_from_vindr(ann_csv, images_root, split, per_class, limit, seed):
    studies = defaultdict(lambda: {"views": {}, "labels": {}})
    with open(ann_csv, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if split and r.get("split", "").strip().lower() != split:
                continue
            st = studies[r["study_id"]]
            side, view = r["laterality"].strip().upper()[:1], r["view_position"].strip().upper()
            if side in ("L", "R") and view in ("CC", "MLO"):
                st["views"][(side, view)] = r["image_id"]
                st["labels"][side] = _birads(r.get("breast_birads"))
    ids = sorted(studies)
    random.Random(seed).shuffle(ids)
    picked, count = [], defaultdict(int)
    for sid in ids:                                     # balanced: keep a study while one of its breasts is a class
        labs = [l for l in studies[sid]["labels"].values() if l]   # that still needs examples
        if per_class and not any(count[l] < per_class for l in labs):
            continue
        picked.append(sid)
        for l in labs:
            count[l] += 1
        if limit and len(picked) >= limit:
            break
        if per_class and all(count[k] >= per_class for k in range(1, K + 1)):
            break
    cases, missing = [], 0
    for sid in picked:
        st = studies[sid]
        paths = {}
        for key, image_id in st["views"].items():
            p = _find_image(images_root, sid, image_id)
            if p:
                paths[key] = p
            else:
                missing += 1
        if paths:
            cases.append({"study_id": sid, "paths": paths, "labels": st["labels"]})
    if missing:
        print(f"note: {missing} image file(s) listed in the CSV were not found under {images_root}")
    return cases


def cases_from_csv(path):
    cases = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            paths = {}
            for side in ("L", "R"):
                for view in ("CC", "MLO"):
                    p = (r.get(f"{side}_{view}") or "").strip()
                    if p:
                        paths[(side, view)] = p
            cases.append({"study_id": r["study_id"].strip(), "paths": paths,
                          "labels": {"L": _birads(r.get("birads_L")), "R": _birads(r.get("birads_R"))}})
    return cases


# --------------------------------------------------------------------------
# Running the device pipeline
# --------------------------------------------------------------------------
def run_cases(cases):
    import atlas_convert
    import atlas_preprocess
    import atlas_models

    ens = atlas_models.get_ensemble()
    t0 = time.time()
    print("loading the networks ...", flush=True)
    ens.load()
    print(f"loaded {ens.n_networks} networks in {time.time() - t0:.0f} s", flush=True)

    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, case in enumerate(cases, 1):
            canvases = {}
            for key, src in case["paths"].items():
                try:
                    png = atlas_convert.convert_to_png(src, tmp, stem=f"{case['study_id']}_{key[0]}_{key[1]}").png_path
                    res = atlas_preprocess.process_image(png)
                except Exception as exc:
                    res = None
                    print(f"  {case['study_id']} {key[0]} {key[1]}: cannot read ({exc})")
                if res is not None:
                    canvases[key] = res[0]
            slots = atlas_preprocess.fill_slots({k: k for k in canvases})
            if not slots:
                print(f"[{i}/{len(cases)}] {case['study_id']}: no readable views, skipped")
                continue
            sides = sorted({s for s, _v in canvases})
            t1 = time.time()
            probs = atlas_models.run_ensemble({slot: canvases[src] for slot, src in slots.items()}, sides)
            secs = time.time() - t1
            for side in sides:
                p = probs[side]
                true = case["labels"].get(side)
                pred = int(np.argmax(p)) + 1
                rows.append({"study_id": case["study_id"], "side": side, "true": true or "", "pred": pred,
                             **{f"p{k + 1}": f"{p[k]:.6f}" for k in range(K)}, "seconds": f"{secs:.1f}"})
                print(f"[{i}/{len(cases)}] {case['study_id']} {side}: predicted B{pred}"
                      f" ({100 * max(p):.0f}%), true {('B' + str(true)) if true else '?'}   {secs:.0f} s", flush=True)
    return rows


def read_predictions(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        if not r.get("pred"):
            r["pred"] = int(np.argmax([float(r[f"p{k}"]) for k in range(1, K + 1)])) + 1
    return rows


# --------------------------------------------------------------------------
# Metrics (numpy only)
# --------------------------------------------------------------------------
def auc(scores, positives):
    """ROC AUC by the rank (Mann-Whitney) formula; ties get the average rank.  None if one group is empty."""
    s, y = np.asarray(scores, float), np.asarray(positives, bool)
    n_pos, n_neg = int(y.sum()), int((~y).sum())
    if n_pos == 0 or n_neg == 0:
        return None
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s))
    ss = s[order]
    i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and ss[j + 1] == ss[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return (ranks[y].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def metrics(rows):
    rows = [r for r in rows if _birads(r.get("true"))]
    if not rows:
        return None
    y = np.array([_birads(r["true"]) for r in rows]) - 1
    yh = np.array([int(r["pred"]) for r in rows]) - 1
    P = np.array([[float(r[f"p{k}"]) for k in range(1, K + 1)] for r in rows])
    n = len(y)

    cm = np.zeros((K, K), int)
    for a, b in zip(y, yh):
        cm[a, b] += 1
    per = []
    for k in range(K):
        tp, fp, fn = cm[k, k], cm[:, k].sum() - cm[k, k], cm[k, :].sum() - cm[k, k]
        prec = tp / (tp + fp) if tp + fp else None
        rec = tp / (tp + fn) if tp + fn else None
        f1 = 2 * prec * rec / (prec + rec) if prec and rec else (0.0 if (prec is not None and rec is not None) else None)
        per.append({"class": NAMES[k], "support": int(cm[k].sum()), "precision": prec, "recall": rec, "f1": f1,
                    "auc": auc(P[:, k], y == k)})

    # quadratic weighted kappa: agreement that gives partial credit for near misses (B2 vs B3) on an ordered scale
    W = np.array([[(i - j) ** 2 for j in range(K)] for i in range(K)]) / (K - 1) ** 2
    E = np.outer(cm.sum(1), cm.sum(0)) / n
    qwk = 1 - (W * cm).sum() / (W * E).sum() if (W * E).sum() else None

    # suspicious (B4-B5) versus not (B1-B3): the clinically important split
    sus_true, sus_pred, sus_score = y >= 3, yh >= 3, P[:, 3] + P[:, 4]
    tp, fn = int((sus_true & sus_pred).sum()), int((sus_true & ~sus_pred).sum())
    tn, fp = int((~sus_true & ~sus_pred).sum()), int((~sus_true & sus_pred).sum())

    # calibration: expected calibration error over 10 confidence bins
    conf, correct = P.max(1), (yh == y)
    bins, ece = [], 0.0
    for lo in np.arange(0, 1, 0.1):
        m = (conf > lo) & (conf <= lo + 0.1)
        if m.any():
            bins.append((lo, lo + 0.1, int(m.sum()), float(conf[m].mean()), float(correct[m].mean())))
            ece += m.sum() / n * abs(conf[m].mean() - correct[m].mean())

    f1s = [p["f1"] for p in per if p["support"] and p["f1"] is not None]
    aucs = [p["auc"] for p in per if p["auc"] is not None]
    return {
        "n": n, "cm": cm, "per": per, "accuracy": float(correct.mean()),
        "within_one": float((np.abs(yh - y) <= 1).mean()), "macro_f1": float(np.mean(f1s)) if f1s else None,
        "macro_auc": float(np.mean(aucs)) if aucs else None, "qwk": qwk,
        "sens": tp / (tp + fn) if tp + fn else None, "spec": tn / (tn + fp) if tn + fp else None,
        "sus_auc": auc(sus_score, sus_true), "sus_counts": (tp, fn, tn, fp), "ece": ece, "bins": bins,
    }


def compare(rows, notebook_csv):
    ref = {}
    with open(notebook_csv, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            ref[(r["study_id"].strip(), r["side"].strip().upper()[:1])] = np.array([float(r[f"p{k}"]) for k in range(1, K + 1)])
    diffs, agree, n = [], 0, 0
    for r in rows:
        q = ref.get((r["study_id"], r["side"]))
        if q is None:
            continue
        p = np.array([float(r[f"p{k}"]) for k in range(1, K + 1)])
        diffs.append(float(np.abs(p - q).max()))
        agree += int(np.argmax(p) == np.argmax(q))
        n += 1
    return n, agree, diffs


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
def _f(v, pct=False):
    if v is None:
        return "  n/a"
    return f"{100 * v:5.1f}%" if pct else f"{v:.3f}"


def report(rows, m, cmp):
    out = []
    w = out.append
    w("ATLAS-BC evaluation report")
    w("=" * 60)
    secs = [float(r["seconds"]) for r in rows if r.get("seconds")]
    w(f"breasts scored: {len(rows)}" + (f"   (time per scan: median {np.median(secs):.0f} s, max {max(secs):.0f} s)"
                                         if secs else ""))
    if cmp:
        n, agree, diffs = cmp
        w("")
        w("1. DEVICE vs NOTEBOOK (same images)")
        if n:
            w(f"   matched breasts: {n}   same BI-RADS: {agree}/{n}   largest probability difference: {max(diffs):.4f}")
            w("   PASS: the device reproduces the notebook." if agree == n and max(diffs) < 0.01 else
              "   CHECK: the device differs from the notebook; compare preprocessing, view order and model files.")
        else:
            w("   no study_id/side pairs in common with the notebook file")
    if not m:
        w("")
        w("No true labels given, so no accuracy metrics (fill birads_L / birads_R).")
        return "\n".join(out)
    w("")
    w(f"2. HOW GOOD ARE THE PREDICTIONS   (n = {m['n']} breasts with a known BI-RADS)")
    w(f"   accuracy (exact BI-RADS):        {_f(m['accuracy'], True)}")
    w(f"   within one level:                {_f(m['within_one'], True)}")
    w(f"   macro F1:                        {_f(m['macro_f1'])}")
    w(f"   macro AUC (one class vs rest):   {_f(m['macro_auc'])}")
    w(f"   quadratic weighted kappa:        {_f(m['qwk'])}")
    w("")
    tp, fn, tn, fp = m["sus_counts"]
    w("   Suspicious (B4-B5) vs not (B1-B3):")
    w(f"     sensitivity (cancers caught):  {_f(m['sens'], True)}   ({tp} caught, {fn} missed)")
    w(f"     specificity (normals cleared): {_f(m['spec'], True)}   ({tn} cleared, {fp} false alarms)")
    w(f"     AUC (score = P4 + P5):         {_f(m['sus_auc'])}")
    w("")
    w("   Per class        n  precision  recall      F1    AUC")
    for p in m["per"]:
        w(f"   {p['class']:<10} {p['support']:5d}     {_f(p['precision'], True)}  {_f(p['recall'], True)}"
          f"   {_f(p['f1'])}  {_f(p['auc'])}")
    w("")
    w("   Confusion matrix (rows = true, columns = predicted)")
    w("            " + "".join(f"{c:>6}" for c in NAMES))
    for k in range(K):
        w(f"   true {NAMES[k]:<4} " + "".join(f"{v:6d}" for v in m["cm"][k]))
    w("")
    w(f"   Calibration: expected calibration error {_f(m['ece'], True)}  (0% = confidence matches accuracy)")
    w("     confidence bin   n   mean confidence   actually right")
    for lo, hi, n, c, a in m["bins"]:
        w(f"     {100 * lo:3.0f}-{100 * hi:3.0f}%     {n:4d}        {100 * c:5.1f}%          {100 * a:5.1f}%")
    if m["n"] < 50:
        w("")
        w(f"   Note: with only {m['n']} breasts these numbers move a lot from one sample to the next;")
        w("   report the notebook's full test-set metrics as the main result and this run as the on-device check.")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--vindr", help="VinDr-Mammo breast-level_annotations.csv")
    src.add_argument("--cases", help="your own cases CSV (see the top of this file)")
    src.add_argument("--predictions", help="score an existing predictions CSV, run nothing")
    ap.add_argument("--images", help="with --vindr: the images folder (images/<study_id>/<image_id>.dicom)")
    ap.add_argument("--split", default="test", help="with --vindr: which split (default test)")
    ap.add_argument("--per-class", type=int, default=4, help="with --vindr: breasts per BI-RADS class (default 4)")
    ap.add_argument("--limit", type=int, default=0, help="at most this many studies")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--compare", help="notebook predictions CSV: study_id,side,p1..p5")
    ap.add_argument("--out", default=".", help="folder for atlas_eval_predictions.csv and atlas_eval_report.txt")
    a = ap.parse_args()

    if a.predictions:
        rows = read_predictions(a.predictions)
    else:
        if a.vindr:
            if not a.images:
                ap.error("--vindr needs --images")
            cases = cases_from_vindr(a.vindr, a.images, a.split.lower(), a.per_class, a.limit, a.seed)
        else:
            cases = cases_from_csv(a.cases)[: a.limit or None]
        if not cases:
            sys.exit("no cases to run")
        n_breasts = sum(len({s for s, _ in c["paths"]}) for c in cases)
        print(f"{len(cases)} studies, {n_breasts} breasts", flush=True)
        rows = run_cases(cases)
        os.makedirs(a.out, exist_ok=True)
        pred_path = os.path.join(a.out, "atlas_eval_predictions.csv")
        with open(pred_path, "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=["study_id", "side", "true", "pred"] + [f"p{k}" for k in range(1, K + 1)]
                                + ["seconds"])
            wr.writeheader()
            wr.writerows(rows)
        print(f"\npredictions: {pred_path}")

    text = report(rows, metrics(rows), compare(rows, a.compare) if a.compare else None)
    rep_path = os.path.join(a.out, "atlas_eval_report.txt")
    os.makedirs(a.out, exist_ok=True)
    with open(rep_path, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print("\n" + text + f"\n\nreport: {rep_path}")


if __name__ == "__main__":
    main()
