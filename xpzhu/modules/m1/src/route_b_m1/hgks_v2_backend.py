"""M1 核心后端：已预处理候选池 -> 冻结HGKS V2 -> 选中时间点。

从这里开始阅读：preflight() -> run_cached() -> _validated_selection()。
输入：1020里的DEV/TEST portable候选池、冻结.joblib模型和其专用Python。
处理：只做源文件/版本检查，调用原版 predict.py，验证模型回执和结果。
输出：M1/HGKS_SELECTED_TIMESTAMPS.json，含video_id、K、time_s及哈希。
失败：模型哈希不符、协议不支持、预测进程失败或输出不满足冻结契约。

Hand/Object/Coarse特征已经存在于预处理池；本文件既不产生掩码，
也不复制141维特征公式和HGB选帧算法。它不会生成JPEG或BT。
"""
import math
import subprocess
from pathlib import Path
from typing import Any, Dict

from .io_utils import read_json, sha256_file, write_json

CONFIG_SCHEMA = "m1_hgks_v2_cached_config_v1"
ALGORITHM = "HGKS_LITE_SINGLE_HGB_V2_OBJECT_BIN"
PREDICTION_SCHEMA = "HGKS_FINAL_PREDICTION_V1"


def _file(path: str, label: str) -> Path:
    candidate = Path(path).expanduser().resolve()
    if not candidate.is_file():
        raise FileNotFoundError("%s_missing:%s" % (label, candidate))
    return candidate


def preflight(config: Dict[str, Any]) -> Dict[str, Any]:
    """输入：M1配置；输出：已解析的输入/模型路径和哈希。

    这里只核验路径、发布版本与模型字节身份；1020代码自己核验运行环境
    和portable数据。preflight通过不等于推断成功，不能标记已选帧。
    """
    if config.get("schema_version") != CONFIG_SCHEMA:
        raise ValueError("unsupported_hgks_m1_config")
    split = config.get("expected_split")
    if split not in ("DEV", "TEST"):
        raise ValueError("expected_split_must_be_DEV_or_TEST")
    root = Path(config["hgks_root"]).expanduser().resolve()
    python = _file(config["python_executable"], "hgks_python")
    source = _file(config["input_bundle"], "hgks_input")
    _file(str(root / "tools" / "run_hgks.py"), "hgks_launcher")
    _file(str(root / "predict.py"), "hgks_predict")
    _file(str(root / "paths.json"), "hgks_paths")
    release = read_json(_file(str(root / "ACTIVE_HGKS_RELEASE.json"), "hgks_release"))
    if release.get("model_bundle_version") != ALGORITHM:
        raise ValueError("unexpected_hgks_model_version")
    model = _file(str(root / release["model_path"]), "hgks_model")
    _file(str(model.parent / "TRAIN_RECEIPT.json"), "hgks_train_receipt")
    model_sha = sha256_file(model)
    if model_sha != release["model_sha256"]:
        raise ValueError("hgks_model_sha256_mismatch")
    count = config.get("expected_videos")
    if count is not None and (type(count) is not int or count < 1):
        raise ValueError("expected_videos_must_be_positive_int")
    return {
        "schema_version": "m1_hgks_v2_preflight_v1",
        "status": "PASS",
        "scope": split,
        "python": str(python),
        "hgks_root": str(root),
        "input_bundle": str(source),
        "model": str(model),
        "input_sha256": sha256_file(source),
        "model_sha256": model_sha,
        "predict_source_sha256": sha256_file(root / "predict.py"),
        "launcher_sha256": sha256_file(root / "tools" / "run_hgks.py"),
        "expected_videos": count,
        "runtime_verified": False,
    }


def _validated_selection(prediction: Dict[str, Any], receipt: Dict[str, Any],
                         checked: Dict[str, Any], prediction_sha: str) -> Dict[str, Any]:
    """输入：1020正式预测与Selection回执；输出：M1可追溯的选帧清单。

    逐视频检查K预算、时间单调、候选索引唯一和来源一致性；不重算预测。
    """
    # 不重新计算HGKS评分，只检查输出是否确实来自指定输入和模型。
    if prediction.get("schema") != PREDICTION_SCHEMA:
        raise ValueError("unknown_hgks_prediction_schema")
    if prediction.get("algorithm_version") != ALGORITHM:
        raise ValueError("unexpected_hgks_algorithm")
    if prediction.get("split") != checked["scope"]:
        raise ValueError("hgks_prediction_split_mismatch")
    if prediction.get("input_sha256") != checked["input_sha256"] or \
       prediction.get("model_sha256") != checked["model_sha256"]:
        raise ValueError("hgks_prediction_provenance_mismatch")
    if receipt.get("prediction_sha256") != prediction_sha or \
       receipt.get("input_sha256") != checked["input_sha256"] or \
       receipt.get("model_sha256") != checked["model_sha256"] or \
       receipt.get("algorithm_version") != ALGORITHM:
        raise ValueError("hgks_selection_receipt_mismatch")
    if receipt.get("status") != "FROZEN_UNLABELED_INFERENCE":
        raise ValueError("hgks_selection_not_frozen_inference")
    if prediction.get("QA_or_Fine_at_inference") is not False:
        raise ValueError("hgks_inference_gold_leakage_flag")
    videos = prediction.get("predictions")
    if not isinstance(videos, dict) or not videos or prediction.get("n_videos") != len(videos):
        raise ValueError("hgks_prediction_video_count_mismatch")
    if checked["expected_videos"] is not None and len(videos) != checked["expected_videos"]:
        raise ValueError("hgks_expected_video_count_mismatch")
    rows = []
    for video_id, entry in sorted(videos.items()):
        duration = entry.get("duration_s")
        selected = entry.get("selected")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
            raise ValueError("hgks_invalid_video_duration")
        if not isinstance(selected, list) or len(selected) != entry.get("K") or not selected:
            raise ValueError("hgks_invalid_selected_count")
        # Formal predict.select_video uses the frozen ceil(duration / 30) budget.
        # The historical K32 Claude experiments are a different experiment setup.
        if len(selected) != math.ceil(duration / 30.0):
            raise ValueError("hgks_frozen_budget_mismatch")
        candidate_indices = [row.get("candidate_index") for row in selected]
        if len(candidate_indices) != len(set(candidate_indices)):
            raise ValueError("hgks_duplicate_selected_candidate")
        previous = -1.0
        for item in selected:
            timestamp = item.get("time_s")
            if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp) or \
               not previous < timestamp < duration:
                raise ValueError("hgks_invalid_selected_timestamp")
            if type(item.get("candidate_index")) is not int or item["candidate_index"] < 0:
                raise ValueError("hgks_invalid_candidate_index")
            previous = timestamp
        rows.append({
            "video_id": video_id,
            "duration_s": duration,
            "K": len(selected),
            "selected": selected,
            "candidate_times_digest": entry.get("candidate_times_digest"),
        })
    return {
        "schema_version": "m1_hgks_v2_selected_timestamps_v1",
        "algorithm_version": ALGORITHM,
        "input_bundle_sha256": checked["input_sha256"],
        "model_sha256": checked["model_sha256"],
        "prediction_sha256": prediction_sha,
        "image_materialized": False,
        "video_count": len(rows),
        "selected_timestamp_count": sum(row["K"] for row in rows),
        "videos": rows,
    }


def run_cached(run_root: Path, config: Dict[str, Any], preflight_only: bool = False) -> Dict[str, Any]:
    """输入：Run目录和已预处理的数据配置；输出：选中时间戳Manifest。

    执行顺序：preflight -> 1020独立Python调用predict.py -> 读取结果与
    TRAIN/selection回执 -> 校验SHA和K/时间/索引 -> 写入Run。
    不调用Claude、不提取帧，模型权重和研究算法均保持原样。
    """
    checked = preflight(config)
    run_root = Path(run_root).resolve()
    write_json(run_root / "m1" / "HGKS_PREFLIGHT.json", checked)
    if preflight_only:
        return {"status": "PASS", "mode": "hgks_v2_cached", "preflight_only": True,
                "selection_performed": False, "model_sha256": checked["model_sha256"]}

    output_root = run_root / "m1" / "hgks_v2_prediction"
    if output_root.exists():
        raise FileExistsError("hgks_output_already_exists:%s" % output_root)
    command = [checked["python"], "-B", str(Path(checked["hgks_root"]) / "tools" / "run_hgks.py"),
               "predict.py", "--input", checked["input_bundle"],
               "--model", checked["model"], "--out", str(output_root),
               "--expected-split", checked["scope"]]
    if checked["expected_videos"] is not None:
        command += ["--expected-videos", str(checked["expected_videos"])]
    try:
        result = subprocess.run(command, cwd=checked["hgks_root"], capture_output=True,
                                text=True, shell=False, timeout=1800, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("hgks_inference_timed_out") from exc
    write_json(run_root / "m1" / "HGKS_PROCESS.json", {
        "returncode": result.returncode,
        "stdout_tail": result.stdout[-4000:],
        "stderr_tail": result.stderr[-4000:],
    })
    if result.returncode != 0:
        raise RuntimeError("hgks_inference_failed:see_HGKS_PROCESS.json")
    prediction_path = output_root / (checked["scope"] + "_LITE_FROZEN.json")
    receipt_path = output_root / (checked["scope"] + "_SELECTION_RECEIPT.json")
    prediction = read_json(prediction_path)
    receipt = read_json(receipt_path)
    selected = _validated_selection(prediction, receipt, checked, sha256_file(prediction_path))
    # The source must not change while inference is running.
    if sha256_file(Path(checked["input_bundle"])) != checked["input_sha256"]:
        raise RuntimeError("hgks_input_changed_during_inference")
    write_json(run_root / "m1" / "HGKS_SELECTED_TIMESTAMPS.json", selected)
    return {"status": "PASS", "mode": "hgks_v2_cached", "preflight_only": False,
            "selection_performed": True, "video_count": selected["video_count"],
            "selected_timestamp_count": selected["selected_timestamp_count"],
            "model_sha256": checked["model_sha256"],
            "prediction_path": str(prediction_path),
            "selected_manifest_path": str(run_root / "m1" / "HGKS_SELECTED_TIMESTAMPS.json"),
            "packet_root": None, "image_materialized": False,
            "m2_dataset_ready": False, "runtime_verified": True}
