"""Check selected timestamp -> image identity, not HGKS model performance."""
import json
from pathlib import Path

import pytest
from PIL import Image

from route_b_m1.hgks_images import materialize_images
from route_b_m1.io_utils import sha256_file


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def selection():
    return {"schema_version": "m1_hgks_v2_selected_timestamps_v1",
            "videos": [{"video_id": "sample", "selected": [
                {"time_s": 1.25, "candidate_index": 2},
                {"time_s": 3.25, "candidate_index": 5}]}]}


def test_indexed_jpegs_get_verified_and_copied(tmp_path):
    a, b = tmp_path / "a.jpg", tmp_path / "b.jpg"
    Image.new("RGB", (32, 24), (255, 0, 0)).save(a, format="JPEG")
    Image.new("RGB", (32, 24), (0, 255, 0)).save(b, format="JPEG")
    selected = tmp_path / "selected.json"
    sources = tmp_path / "sources.json"
    save_json(selected, selection())
    save_json(sources, {"schema_version": "m1_hgks_frame_sources_v1",
                         "videos": {"sample": {"mode": "indexed_jpegs", "timebase": "hgks_selection_seconds", "frames": [
                             {"timestamp_s": 1.26, "path": str(a), "sha256": sha256_file(a)},
                             {"timestamp_s": 3.27, "path": str(b), "sha256": sha256_file(b)}
                         ]}}})
    out = tmp_path / "images"
    result = materialize_images(selected, sources, out, tolerance_s=0.05)
    assert [round(i["timestamp_s"], 2) for i in result["videos"][0]["images"]] == [1.26, 3.27]
    assert (out / "sample" / "0001.jpg").read_bytes() == a.read_bytes()
    assert (out / "M1_SELECTED_IMAGES.json").is_file()


def test_missing_frame_is_not_silently_dropped(tmp_path):
    f = tmp_path / "a.jpg"
    Image.new("RGB", (16, 16), (0, 0, 255)).save(f, format="JPEG")
    selected = tmp_path / "selected.json"
    sources = tmp_path / "sources.json"
    save_json(selected, selection())
    save_json(sources, {"schema_version": "m1_hgks_frame_sources_v1",
                         "videos": {"sample": {"mode": "indexed_jpegs", "timebase": "hgks_selection_seconds", "frames": [
                             {"timestamp_s": 1.25, "path": str(f), "sha256": sha256_file(f)}
                         ]}}})
    with pytest.raises(ValueError, match="no_jpeg_within_tolerance|no_unused_jpeg_for_selection"):
        materialize_images(selected, sources, tmp_path / "images")
    assert not (tmp_path / "images").exists()


def test_rejects_tampered_image(tmp_path):
    f = tmp_path / "a.jpg"
    Image.new("RGB", (16, 16), (0, 0, 255)).save(f, format="JPEG")
    selected = tmp_path / "selected.json"
    sources = tmp_path / "sources.json"
    save_json(selected, {"schema_version": "m1_hgks_v2_selected_timestamps_v1",
                         "videos": [{"video_id": "sample", "selected": [
                             {"time_s": 1.25, "candidate_index": 2}]}]})
    save_json(sources, {"schema_version": "m1_hgks_frame_sources_v1",
                         "videos": {"sample": {"mode": "indexed_jpegs", "timebase": "hgks_selection_seconds", "frames": [
                             {"timestamp_s": 1.25, "path": str(f), "sha256": "0" * 64}
                         ]}}})
    with pytest.raises(ValueError, match="jpeg_sha256_mismatch"):
        materialize_images(selected, sources, tmp_path / "images")


def test_nearest_used_jpeg_selects_another_valid_frame(tmp_path):
    paths = [tmp_path / name for name in ("a.jpg", "b.jpg")]
    for i, path in enumerate(paths):
        Image.new("RGB", (8, 8), (i * 255, 0, 0)).save(path, format="JPEG")
    selected = tmp_path / "selected.json"
    sources = tmp_path / "sources.json"
    save_json(selected, {"schema_version": "m1_hgks_v2_selected_timestamps_v1",
                         "videos": [{"video_id": "sample", "selected": [
                             {"time_s": 1.0, "candidate_index": 0},
                             {"time_s": 1.02, "candidate_index": 1}]}]})
    save_json(sources, {"schema_version": "m1_hgks_frame_sources_v1",
                         "videos": {"sample": {"mode": "indexed_jpegs",
                             "timebase": "hgks_selection_seconds", "frames": [
                                 {"timestamp_s": 1.0, "path": str(paths[0]),
                                  "sha256": sha256_file(paths[0])},
                                 {"timestamp_s": 1.04, "path": str(paths[1]),
                                  "sha256": sha256_file(paths[1])}]}}})
    result = materialize_images(selected, sources, tmp_path / "out", tolerance_s=0.05)
    assert len(result["videos"][0]["images"]) == 2
    assert (tmp_path / "out" / "sample" / "0002.jpg").read_bytes() == paths[1].read_bytes()


def test_invalid_jpeg_header_is_rejected(tmp_path):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"\xff\xd8\xffnot_an_image")
    selected = tmp_path / "selected.json"
    sources = tmp_path / "sources.json"
    save_json(selected, {"schema_version": "m1_hgks_v2_selected_timestamps_v1",
                         "videos": [{"video_id": "sample", "selected": [
                             {"time_s": 1.0, "candidate_index": 0}]}]})
    save_json(sources, {"schema_version": "m1_hgks_frame_sources_v1",
                         "videos": {"sample": {"mode": "indexed_jpegs",
                             "timebase": "hgks_selection_seconds", "frames": [
                                 {"timestamp_s": 1.0, "path": str(bad),
                                  "sha256": sha256_file(bad)}]}}})
    with pytest.raises(ValueError, match="jpeg_decode_failed"):
        materialize_images(selected, sources, tmp_path / "out")


def test_materialize_one_video_without_other_videos_sources(tmp_path):
    image = tmp_path / "one.jpg"
    Image.new("RGB", (12, 10), (0, 100, 0)).save(image, format="JPEG")
    selected = tmp_path / "selection.json"
    sources = tmp_path / "sources.json"
    save_json(selected, {"schema_version": "m1_hgks_v2_selected_timestamps_v1",
                         "videos": [
                             {"video_id": "chosen", "selected": [
                                 {"time_s": 1.0, "candidate_index": 0}]},
                             {"video_id": "other", "selected": [
                                 {"time_s": 1.0, "candidate_index": 0}]},
                         ]})
    save_json(sources, {"schema_version": "m1_hgks_frame_sources_v1",
                         "videos": {"chosen": {"mode": "indexed_jpegs",
                             "timebase": "hgks_selection_seconds", "frames": [
                                 {"timestamp_s": 1.0, "path": str(image),
                                  "sha256": sha256_file(image)}]}}})
    result = materialize_images(selected, sources, tmp_path / "out", video_id="chosen")
    assert [row["video_id"] for row in result["videos"]] == ["chosen"]
