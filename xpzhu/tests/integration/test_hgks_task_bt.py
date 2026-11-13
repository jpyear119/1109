"""Test task proposal -> XML with no Claude API call or robot runtime."""
import json
import hashlib
from PIL import Image
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from route_b_m6b.task_draft import compile_draft_ir, export_candidate


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def make_job(tmp_path):
    job = tmp_path / "job"
    (job / "images").mkdir(parents=True)
    images = []
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
            separators=(",", ":")).encode("utf-8")).hexdigest()
    for i in range(1, 3):
        path = job / "images" / ("%04d.jpg" % i)
        Image.new("RGB", (8, 8), (i * 80, 0, 0)).save(path, format="JPEG")
        images.append({"order": i, "file": path.name, "timestamp_s": float(i),
                       "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                       "bytes": path.stat().st_size, "width": 8, "height": 8})
    manifest_hash = digest(images)
    save_json(job / "MANIFEST.json", {"manifest_sha256": manifest_hash,
                                      "count": 2, "images": images})
    prompt = "Dummy prompt only for contract tests."
    sop = "Dummy SOP only for contract tests."
    (job / "PROMPT.md").write_text(prompt, encoding="utf-8")
    (job / "SOP.md").write_text(sop, encoding="utf-8")
    schema = {"title": "FixtureSchema", "type": "object"}
    save_json(job / "SCHEMA.json", schema)
    save_json(job / "REQUEST.json", {
        "job_id": "TEST_PC", "video_id": "PC_SAMPLE", "prompt_family": "PC_D",
        "segment_start_s": 0, "segment_end_s": 3,
        "manifest_sha256": manifest_hash,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "sop_sha256": hashlib.sha256(sop.encode()).hexdigest(),
        "schema": {"schema_sha256": digest(schema)}, "k_images": 2})
    save_json(job / "RECEIPT.json", {"ingested": True, "blocked_reasons": [],
        "status": "OK", "returncode": 0, "k_images": 2,
        "model_id_actual": "test-model",
        "n_events": 1, "manifest_sha256": manifest_hash,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()})
    save_json(job / "BT_OUTPUT.json", {
        "video_id": "PC_SAMPLE", "segment_start_s": 0, "segment_end_s": 3,
        "events": [{"event_id": "E1", "order": 1, "verb": "lift", "object": "cover",
                    "target": "desk", "frame_indices": [1], "evidence_basis": "DIRECT",
                    "reason": "cover visible in hand", "uncertainty": 0.1,
                    "before_state": "cover on desk", "after_state": "cover held"}],
        "bt": {"type": "Sequence", "children": [{"type": "Action", "event_id": "E1"}]}})
    return job


def test_draft_xml_requires_explicit_review(tmp_path):
    job = make_job(tmp_path)
    output = tmp_path / "bt_candidate"
    result = export_candidate(job, output)
    assert result["action_count"] == 1
    assert result["reviewed_xml_generated"] is False
    assert (output / "BT_DRAFT_CANDIDATE.xml").is_file()
    assert not (output / "BT_REVIEWED_CANDIDATE.xml").exists()
    xml = ET.parse(output / "BT_DRAFT_CANDIDATE.xml").getroot()
    assert xml.attrib["BTCPP_format"] == "4"
    assert [x.attrib["event_ref"] for x in xml.iter("Action")] == ["E1"]


def test_review_must_approve_all_targets(tmp_path):
    job = make_job(tmp_path)
    ir = compile_draft_ir(job)
    approval = tmp_path / "decisions.json"
    save_json(approval, {"schema_version": "task_draft_review_decisions_v1",
                         "source_job_output_sha256": ir["source_job_output_sha256"],
                         "proposal_sha256": ir["proposal_sha256"],
                         "decisions": []})
    with pytest.raises(ValueError, match="task_review_targets_not_exactly_covered"):
        export_candidate(job, tmp_path / "out", approval)


def test_modified_job_image_must_fail(tmp_path):
    job = make_job(tmp_path)
    (job / "images" / "0001.jpg").write_bytes(b"CHANGED")
    with pytest.raises(ValueError, match="manifest_image_hash_mismatch"):
        compile_draft_ir(job)


def test_explicit_full_approval_produces_reviewed_but_not_executable_xml(tmp_path):
    job = make_job(tmp_path)
    ir = compile_draft_ir(job)
    decisions = tmp_path / "decisions.json"
    save_json(decisions, {
        "schema_version": "task_draft_review_decisions_v1",
        "source_job_output_sha256": ir["source_job_output_sha256"],
        "proposal_sha256": ir["proposal_sha256"],
        "decisions": [{"target_id": x["target_id"], "decision": "accept",
                       "reviewer_id": "human-example", "reviewed_at": "2026-11-13T00:00:00Z",
                       "comment": "Reviewed source frames and control flow."}
                      for x in ir["review_targets"]],
    })
    result = export_candidate(job, tmp_path / "approved", decisions)
    assert result["reviewed_xml_generated"] is True
    assert result["execution_safe"] is False
    assert (tmp_path / "approved" / "BT_REVIEWED_CANDIDATE.xml").is_file()


def test_revision_is_separate_and_invalidates_old_review(tmp_path):
    job = make_job(tmp_path)
    original = compile_draft_ir(job)
    source = json.loads((job / "BT_OUTPUT.json").read_text(encoding="utf-8"))
    source["events"][0]["target"] = "shelf"
    correction = tmp_path / "correction.json"
    save_json(correction, {
        "schema_version": "task_draft_correction_v1",
        "source_job_output_sha256": original["source_job_output_sha256"],
        "author": "reviewer", "reason": "Target location corrected from video evidence",
        "events": source["events"], "bt": source["bt"],
    })
    changed = compile_draft_ir(job, correction)
    assert changed["events"][0]["target"] == "shelf"
    assert changed["proposal_sha256"] != original["proposal_sha256"]
    # The original immutable model output remains unchanged.
    assert json.loads((job / "BT_OUTPUT.json").read_text())["events"][0]["target"] == "desk"


def test_reject_tampered_prompt_even_if_receipt_matches(tmp_path):
    job = make_job(tmp_path)
    (job / "PROMPT.md").write_text("TAMPERED", encoding="utf-8")
    with pytest.raises(ValueError, match="job_prompt_hash_mismatch"):
        compile_draft_ir(job)


def test_reject_tampered_manifest_metadata(tmp_path):
    job = make_job(tmp_path)
    man = json.loads((job / "MANIFEST.json").read_text(encoding="utf-8"))
    man["images"][0]["timestamp_s"] = 9.0
    save_json(job / "MANIFEST.json", man)
    with pytest.raises(ValueError, match="job_manifest_content_hash_mismatch"):
        compile_draft_ir(job)
