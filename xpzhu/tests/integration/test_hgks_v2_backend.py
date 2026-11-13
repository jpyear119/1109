"""Adapter contract tests: use fake prediction artifacts, not a fake trained model."""
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from route_b_m1.hgks_v2_backend import preflight, run_cached
from route_b_m1.io_utils import sha256_file


def _json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _fixture(tmp_path):
    hgks_root = tmp_path / "hgks"
    model = hgks_root / "results" / "ACTIVE_HGKS_V2" / "train" / "HGKS_LITE_MODEL.joblib"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"test-model-not-a-real-joblib")
    _json(model.parent / "TRAIN_RECEIPT.json", {"model_sha256": sha256_file(model)})
    (hgks_root / "tools").mkdir(parents=True)
    (hgks_root / "tools" / "run_hgks.py").write_text("# fake launcher\n")
    (hgks_root / "predict.py").write_text("# fake predictor\n")
    _json(hgks_root / "paths.json", {})
    _json(hgks_root / "ACTIVE_HGKS_RELEASE.json", {
        "model_bundle_version": "HGKS_LITE_SINGLE_HGB_V2_OBJECT_BIN",
        "model_path": str(model.relative_to(hgks_root)),
        "model_sha256": sha256_file(model),
    })
    source = tmp_path / "DEV.json.gz"
    source.write_bytes(b"stand-in-input")
    config = {"schema_version": "m1_hgks_v2_cached_config_v1",
              "hgks_root": str(hgks_root), "python_executable": sys.executable,
              "input_bundle": str(source), "expected_split": "DEV", "expected_videos": 1}
    run_root = tmp_path / "run"
    (run_root / "m1").mkdir(parents=True)
    return run_root, config


def test_preflight_verifies_model_sha_and_does_not_execute(tmp_path):
    run_root, config = _fixture(tmp_path)
    assert preflight(config)["status"] == "PASS"
    result = run_cached(run_root, config, preflight_only=True)
    assert result["selection_performed"] is False
    assert not (run_root / "m1" / "hgks_v2_prediction").exists()


def test_imports_actual_hgks_prediction_contract(tmp_path, monkeypatch):
    run_root, config = _fixture(tmp_path)
    checked = preflight(config)

    def fake_run(command, **kwargs):
        root = Path(command[command.index("--out") + 1])
        root.mkdir()
        prediction_path = root / "DEV_LITE_FROZEN.json"
        _json(prediction_path, {
            "schema": "HGKS_FINAL_PREDICTION_V1",
            "algorithm_version": "HGKS_LITE_SINGLE_HGB_V2_OBJECT_BIN",
            "split": "DEV", "model_sha256": checked["model_sha256"],
            "input_sha256": checked["input_sha256"],
            "QA_or_Fine_at_inference": False, "n_videos": 1,
            "predictions": {"P05": {
                "duration_s": 35.0, "K": 2, "candidate_times_digest": "hash",
                "selected": [
                    {"time_s": 4.25, "candidate_index": 3, "source": "HAND"},
                    {"time_s": 28.25, "candidate_index": 17, "source": "JOINT"},
                ]}}})
        _json(root / "DEV_SELECTION_RECEIPT.json", {
            "status": "FROZEN_UNLABELED_INFERENCE",
            "algorithm_version": "HGKS_LITE_SINGLE_HGB_V2_OBJECT_BIN",
            "model_sha256": checked["model_sha256"],
            "input_sha256": checked["input_sha256"],
            "prediction_sha256": sha256_file(prediction_path),
        })
        return SimpleNamespace(returncode=0, stdout="LITE_SELECTED 1 videos", stderr="")

    monkeypatch.setattr("route_b_m1.hgks_v2_backend.subprocess.run", fake_run)
    result = run_cached(run_root, config)
    assert result["status"] == "PASS"
    assert result["video_count"] == 1
    assert result["selected_timestamp_count"] == 2
    saved = json.loads((run_root / "m1" / "HGKS_SELECTED_TIMESTAMPS.json").read_text())
    assert saved["videos"][0]["selected"][1]["time_s"] == 28.25
    assert saved["image_materialized"] is False


def test_rejects_model_drift(tmp_path):
    _, config = _fixture(tmp_path)
    model = Path(config["hgks_root"]) / "results/ACTIVE_HGKS_V2/train/HGKS_LITE_MODEL.joblib"
    model.write_bytes(b"different-model")
    with pytest.raises(ValueError, match="model_sha256_mismatch"):
        preflight(config)
