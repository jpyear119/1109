"""SOP step times remain attributed context, not video observations."""
import json

import pytest

from route_b_pipeline.sop_steps import render_sop_steps


def test_renders_only_overlapping_steps(tmp_path):
    p = tmp_path / "steps.json"
    p.write_text(json.dumps({
        "schema_version": "pc_task_sop_steps_v1", "video_id": "PC01",
        "steps": [
            {"step_id": "S1", "start_s": 0, "end_s": 10,
             "text": "Inspect device", "time_source": "video_annotation"},
            {"step_id": "S2", "start_s": 10, "end_s": 20,
             "text": "Remove lid", "time_source": "sop_document"},
        ]}), encoding="utf-8")
    result = render_sop_steps(p, "PC01", 10, 20)
    assert result["included_step_count"] == 1
    assert "Remove lid" in result["sop_text"]
    assert "Inspect device" not in result["sop_text"]
    assert "not evidence of action execution" in result["sop_text"]


def test_rejects_wrong_video(tmp_path):
    p = tmp_path / "steps.json"
    p.write_text(json.dumps({"schema_version": "pc_task_sop_steps_v1",
                             "video_id": "OTHER", "steps": [
          {"step_id": "S1", "start_s": 0, "end_s": 5,
           "text": "Inspect", "time_source": "video_annotation"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="sop_video_id_mismatch"):
        render_sop_steps(p, "PC01", 0, 5)
