"""Task flow wiring checks: segment selection must not require all video frames."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from route_b_m1.io_utils import sha256_file


def test_prepare_filters_frames_to_requested_segment(tmp_path, monkeypatch):
    script = Path(__file__).resolve().parents[2] / "tools" / "hgks_task_flow.py"
    spec = importlib.util.spec_from_file_location("hgks_task_flow_for_test", script)
    flow = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(flow)
    monkeypatch.setattr(flow, "ROOT", tmp_path)

    run = tmp_path / "runtime_runs" / "run123"
    images = run / "m1" / "materialized_images"
    images.mkdir(parents=True)
    (run / "RUN_MANIFEST.json").write_text("{}", encoding="utf-8")
    jpeg = images / "one.jpg"
    # For this test, prepare checks existence+hash; actual decoding is tested
    # separately in test_hgks_images.py.
    jpeg.write_bytes(b"sample-file")
    rows = [{"path": str(jpeg), "timestamp_s": t, "image_sha256": sha256_file(jpeg)}
            for t in (2.0, 5.0, 9.0)]
    (images / "M1_SELECTED_IMAGES.json").write_text(json.dumps({
        "videos": [{"video_id": "PC1", "images": rows}]}), encoding="utf-8")

    sop = tmp_path / "sop.json"
    sop.write_text(json.dumps({"schema_version": "pc_task_sop_steps_v1",
                               "video_id": "PC1", "steps": [{
                                   "step_id": "S1", "start_s": 3, "end_s": 7,
                                   "text": "Inspect device", "time_source": "video_annotation"
                               }, {
                                   "step_id": "S0", "start_s": 1, "end_s": 3,
                                   "text": "Prepare device", "time_source": "video_annotation"
                               }]}), encoding="utf-8")
    claude_root = tmp_path / "claude"
    (claude_root / "tools").mkdir(parents=True)
    (claude_root / "claude_vision").mkdir()
    (claude_root / "tools" / "run_hgks.py").write_text("")
    (claude_root / "claude_vision" / "xpzhu_bridge.py").write_text("")
    def fake_run(command, **kwargs):
        job_id = command[command.index("--job-id") + 1]
        images_file = Path(command[command.index("--images") + 1])
        selected_rows = json.loads(images_file.read_text(encoding="utf-8"))
        expected = {"pc_job": [5.0], "pc_job_2": [2.0]}[job_id]
        assert [row["timestamp_s"] for row in selected_rows] == expected
        return SimpleNamespace(returncode=0, stdout="job ready", stderr="")

    monkeypatch.setattr(flow.subprocess, "run", fake_run)
    result = flow.prepare("run123", "PC1", claude_root, tmp_path / "python.exe",
                          sop, 3.0, 7.0, "pc_job", "test_model", 3.0, 30.0)
    assert result["status"] == "JOB_READY_NOT_EXECUTED"
    assert result["frame_count"] == 1
    first_images = (run / "m1" / "CLAUDE_IMAGES_pc_job.json").read_bytes()
    first_sop = (run / "m1" / "TASK_SOP_pc_job.md").read_bytes()

    # Same video, different SOP segment: distinct job IDs must not overwrite data.
    second = flow.prepare("run123", "PC1", claude_root, tmp_path / "python.exe",
                          sop, 1.0, 3.0, "pc_job_2", "test_model", 3.0, 30.0)
    assert second["status"] == "JOB_READY_NOT_EXECUTED"
    assert second["frame_count"] == 1
    assert (run / "m1" / "CLAUDE_IMAGES_pc_job_2.json").is_file()
    assert (run / "m1" / "TASK_SOP_pc_job_2.md").is_file()
    assert (run / "m1" / "CLAUDE_IMAGES_pc_job.json").read_bytes() == first_images
    assert (run / "m1" / "TASK_SOP_pc_job.md").read_bytes() == first_sop

    import pytest
    with pytest.raises(FileExistsError, match="task_preparation_artifacts_already_exist"):
        flow.prepare("run123", "PC1", claude_root, tmp_path / "python.exe",
                     sop, 3.0, 7.0, "pc_job", "test_model", 3.0, 30.0)
