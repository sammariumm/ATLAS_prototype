"""Tests of the AI part (atlas_models.py).

* The tests that need PyTorch skip themselves when it is not installed.
* The tests that run the REAL 15-network ensemble skip themselves when the model files are not there
  (set ATLAS_MODELS_DIR, or put the folder next to app.py as `models/`).
"""
import json
import os

import numpy as np
import pytest

import synth
import atlas_models
import atlas_preprocess

import app as backend


def _post(client, url, **body):
    r = client.post(url, data=json.dumps(body), content_type="application/json")
    return r.status_code, r.get_json()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "SAVE_DIR", str(tmp_path / "scans"))
    monkeypatch.setattr(backend, "INBOX_DIR", str(tmp_path / "inbox"))
    os.makedirs(backend.INBOX_DIR)
    backend.app.config["TESTING"] = True
    return backend.app.test_client()


def _real_models_present():
    try:
        atlas_models.Ensemble().check_files()
        return True
    except atlas_models.ModelsUnavailable:
        return False


needs_weights = pytest.mark.skipif(not _real_models_present(), reason="model files not found (ATLAS_MODELS_DIR)")


def _canvases(seed0=1):
    """Four preprocessed inputs (different synthetic breasts) in the order L-CC, L-MLO, R-CC, R-MLO."""
    out = {}
    for i, (side, view) in enumerate(atlas_models.SLOTS):
        img = synth.make_digital(side=side, seed=seed0 + i)
        out[(side, view)] = atlas_preprocess.process_array(img)[0]
    return out


# ------------------------------------------------------------------------------------- pure maths ----
def test_weighted_average_normalises_the_weights():
    a, b, c = (np.array([[1.0, 0, 0, 0, 0]]), np.array([[0, 1.0, 0, 0, 0]]), np.array([[0, 0, 1.0, 0, 0]]))
    out = atlas_models.wa_aggregate([a, b, c], [0.4486, 0.1980, 0.3534])
    assert np.allclose(out, [[0.4486, 0.1980, 0.3534, 0, 0]] / np.float64(0.4486 + 0.1980 + 0.3534))
    assert np.allclose(atlas_models.wa_aggregate([a, b], [2, 2]), [[0.5, 0.5, 0, 0, 0]])
    assert np.allclose(atlas_models.combine_probs([a], "wa", {"w": [1]}), a)       # one architecture: unchanged


def test_unknown_combination_is_refused():
    with pytest.raises(ValueError):
        atlas_models.combine_probs([np.ones((1, 5)) / 5] * 2, "sugeno", {})


def test_decision_is_the_most_probable_of_the_five_classes():
    assert atlas_models.decide_five(np.array([0.1, 0.35, 0.3, 0.2, 0.05])) == 1
    assert atlas_models.decide_five(np.array([0.1, 0.2, 0.2, 0.2, 0.3])) == 4


def test_the_shipped_config_is_the_final_ensemble():
    """ensemble_config.json (copy of v3_ensemble/final_config.json) must describe the deployed ensemble."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, "models", atlas_models.CONFIG_NAME)
    if not os.path.isfile(path):
        pytest.skip("models/ensemble_config.json not present")
    cfg = json.load(open(path))
    assert [m["arch"] for m in cfg["members"]] == ["resnet50_in", "densenet121_in", "inception_v3_in"]
    assert all(m["folds"] == [0, 1, 2, 3, 4] for m in cfg["members"])
    assert cfg["combine"] == "wa" and cfg["decide"] == "five"
    assert len(cfg["calibration"]["w"]) == 3 and abs(sum(cfg["calibration"]["w"]) - 1.0) < 1e-6
    assert (cfg["img_h"], cfg["img_w"], cfg["use_clahe"]) == (atlas_models.IMG_H, atlas_models.IMG_W, atlas_preprocess.USE_CLAHE)


# ------------------------------------------------------------------------------------ missing files ----
def test_missing_model_folder_gives_a_clear_error(tmp_path):
    with pytest.raises(atlas_models.ModelsUnavailable, match="not found"):
        atlas_models.Ensemble(str(tmp_path)).check_files()


def test_missing_checkpoints_are_listed(tmp_path):
    cfg = {"img_h": 1280, "img_w": 800, "combine": "wa", "calibration": {"w": [1, 1]},
           "members": [{"arch": "resnet50_in", "folds": [0, 1]}, {"arch": "densenet121_in", "folds": [0]}]}
    (tmp_path / atlas_models.CONFIG_NAME).write_text(json.dumps(cfg))
    (tmp_path / "resnet50_in").mkdir()
    (tmp_path / "resnet50_in" / "fold0_best.pth").write_bytes(b"x")
    with pytest.raises(atlas_models.ModelsUnavailable, match=r"2 model file\(s\) missing"):
        atlas_models.Ensemble(str(tmp_path)).check_files()


def test_analyze_never_falls_back_to_random_numbers(client, monkeypatch, tmp_path):
    """Real mode with no model files: the request fails with an explanation, it does not invent a result."""
    monkeypatch.setattr(backend, "MODELS_ARE_MOCK", False)
    monkeypatch.setattr(atlas_models, "_ENSEMBLE", atlas_models.Ensemble(str(tmp_path)))
    import cv2
    cv2.imwrite(os.path.join(backend.INBOX_DIR, "a.png"), synth.make_digital())
    r = _post(client, "/import", scan_id="S1", side="Left", view="CC", source_path="a.png")[1]
    code, j = _post(client, "/analyze", scan_id="S1", views=[dict(side="Left", view="CC", image_path=r["image_path"])])
    assert code == 500 and "AI models failed" in j["error"] and "not found" in j["error"]
    assert "results" not in j


def test_health_reports_the_model_state(client, monkeypatch, tmp_path):
    monkeypatch.setattr(backend, "MODELS_ARE_MOCK", False)
    monkeypatch.setattr(atlas_models, "_ENSEMBLE", atlas_models.Ensemble(str(tmp_path)))
    j = client.get("/health").get_json()
    assert j["models"] == "real" and j["ai"]["loaded"] is False


# --------------------------------------------------------------------------------- network (PyTorch) ----
def test_input_preparation_matches_the_notebook_formulas():
    torch = pytest.importorskip("torch")
    canv = [atlas_preprocess.process_array(synth.make_digital(seed=s))[0] for s in range(4)]
    x, fg = atlas_models.prepare_input(canv)
    assert tuple(x.shape) == (4, 1, 1280, 800) and tuple(fg.shape) == (4, 40, 25) and fg.dtype == torch.bool
    ref = (torch.from_numpy(canv[0]).float() / 255.0 - 0.449) / 0.226
    assert torch.allclose(x[0, 0], ref, atol=1e-6)
    assert float(x[0, 0, -1, -1]) == pytest.approx((0 - 0.449) / 0.226)          # padding stays black
    with pytest.raises(ValueError):
        atlas_models.prepare_input(canv[:3])


def test_smaller_view_chunks_give_the_same_result():
    torch = pytest.importorskip("torch")
    pytest.importorskip("torchvision")
    MammoNet, _ = atlas_models._net_classes()
    torch.manual_seed(0)
    net = MammoNet("densenet121_in").eval()
    x, fg = atlas_models.prepare_input(list(_canvases().values()))
    with torch.inference_mode():
        a = MammoNet.probs(net(x, fg, view_chunk=4))
        b = MammoNet.probs(net(x, fg, view_chunk=1))
    assert torch.allclose(a, b, atol=1e-6) and torch.allclose(a.sum(-1), torch.ones(1, 2), atol=1e-5)


# ------------------------------------------------------------------------- the real 15 networks ----
@needs_weights
def test_real_ensemble_gives_probabilities_for_the_requested_sides():
    ens = atlas_models.Ensemble()
    out = ens.predict(_canvases(), ["L", "R"])
    assert set(out) == {"L", "R"}
    for p in out.values():
        assert len(p) == 5 and abs(sum(p) - 1.0) < 1e-6 and min(p) >= 0
    assert ens.n_networks == 15
    assert set(ens.predict(_canvases(), ["R"])) == {"R"}


@needs_weights
def test_real_ensemble_is_deterministic():
    ens = atlas_models.Ensemble()
    c = _canvases()
    assert ens.predict(c, ["L", "R"]) == ens.predict(c, ["L", "R"])


@needs_weights
def test_analyze_end_to_end_with_the_real_ensemble(client, monkeypatch):
    import cv2
    monkeypatch.setattr(backend, "MODELS_ARE_MOCK", False)
    monkeypatch.setattr(atlas_models, "_ENSEMBLE", atlas_models.Ensemble())
    views = []
    for side, view, seed in (("Left", "CC", 1), ("Left", "MLO", 2), ("Right", "CC", 3), ("Right", "MLO", 4)):
        cv2.imwrite(os.path.join(backend.INBOX_DIR, f"{side}{view}.png"), synth.make_digital(side=side[0], seed=seed))
        r = _post(client, "/import", scan_id="S7", side=side, view=view, source_path=f"{side}{view}.png")[1]
        views.append(dict(side=side, view=view, image_path=r["image_path"]))
    code, j = _post(client, "/analyze", scan_id="S7", views=views)
    assert code == 200 and j["mock"] is False
    assert set(j["results"]) == {"Left", "Right"}
    for res in list(j["results"].values()) + [j["combined"]]:
        assert res["classification"] in atlas_models.CLASS_NAMES and res["confidence"].endswith("%")
        assert "MOCK" not in res["recommendation"]
    assert j["combined"]["basis"] in ("Left breast", "Right breast")
    health = client.get("/health").get_json()
    assert health["ai"]["loaded"] is True and health["ai"]["networks"] == 15 and health["ai"]["combine"] == "wa"
