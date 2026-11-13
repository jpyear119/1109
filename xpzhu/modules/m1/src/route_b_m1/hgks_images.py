"""JPEG映射：HGKS选中时间点 -> 真实JPEG及可校验来源。

阅读 materialize_images() -> _from_index() 或 _from_video()。
输入：HGKS_SELECTED_TIMESTAMPS.json及frame-sources来源清单。
输出：M1_SELECTED_IMAGES.json和实际JPEG，包含请求秒数、物理帧时间、
时间偏差、SHA256。

选帧算法只输出时间点，不保证它对应的JPEG存在；两种来源模式必须提供
明确时间基。官方VRS时间不能冒充MP4相对时钟，无法证明映射则拒绝。
"""
import math
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

from .io_utils import read_json, sha256_file, write_json


SOURCE_SCHEMA = "m1_hgks_frame_sources_v1"
OUTPUT_SCHEMA = "m1_hgks_selected_images_v1"
PTS_RE = re.compile(r"\bpts_time:\s*(-?\d+(?:\.\d+)?)")


def _safe_video_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("unsafe_video_id:%s" % value)
    return value


def _positive_seconds(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError("invalid_%s" % name)
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError("invalid_%s" % name)
    return result


def _source_path(raw: str, root: Path) -> Path:
    path = Path(raw).expanduser()
    return (path if path.is_absolute() else root / path).resolve()


def _checked_jpeg(path: Path, expected_sha: str = None) -> str:
    if not path.is_file() or path.suffix.lower() not in (".jpg", ".jpeg"):
        raise ValueError("jpeg_missing_or_unsupported:%s" % path)
    # A JPEG magic header alone is not an image (old tests allowed malformed
    # 3-byte fixtures). Decode the real image before passing it to Claude.
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:
        raise RuntimeError("pillow_required_for_jpeg_validation") from exc
    try:
        with Image.open(path) as image:
            if image.format != "JPEG":
                raise ValueError("not_a_jpeg:%s" % path)
            image.load()
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError("jpeg_decode_failed:%s" % path) from exc
    actual = sha256_file(path)
    if expected_sha is not None and actual != expected_sha:
        raise ValueError("jpeg_sha256_mismatch:%s" % path)
    return actual


def _from_index(selection_time: float, source: Dict[str, Any], root: Path,
                tolerance_s: float, used: set) -> Dict[str, Any]:
    """在已有JPEG索引中选时间最接近且未使用的图片，超出容差就拒绝。"""
    rows = source.get("frames", [])
    if not isinstance(rows, list) or not rows:
        raise ValueError("frame_index_empty")
    candidates = []
    for item in rows:
        frame_time = _positive_seconds(item.get("timestamp_s"), "frame_timestamp")
        # The official HGKS clock mapping can shift physical frame times.
        # Match against the *requested* time when a receipt supplies it.
        requested = _positive_seconds(item.get("requested_time_s", frame_time),
                                      "requested_frame_timestamp")
        candidates.append((abs(requested - selection_time), frame_time, item))
    # Each selection must receive one distinct JPEG.  A previously used nearest
    # frame must not hide another valid, unused frame inside the tolerance.
    available = [row for row in candidates
                 if str(_source_path(row[2]["path"], root)) not in used]
    if not available:
        raise ValueError("no_unused_jpeg_for_selection:%.6f" % selection_time)
    distance, frame_time, match = min(available, key=lambda r: (r[0], r[1]))
    if distance > tolerance_s:
        raise ValueError("no_jpeg_within_tolerance:%.6f" % selection_time)
    if source["timebase"] == "official_mp4_frames":
        if (type(match.get("official_frame_index")) is not int or
                match["official_frame_index"] < 0 or
                "requested_time_s" not in match):
            raise ValueError("official_frame_mapping_receipt_incomplete")
    path = _source_path(match["path"], root)
    image_hash = _checked_jpeg(path, match.get("sha256"))
    used.add(str(path))
    return {"path": path, "frame_time_s": frame_time, "sha256": image_hash,
            "source_mode": "indexed_jpegs"}


def _from_video(selection_time: float, source: Dict[str, Any], root: Path,
                target: Path, tolerance_s: float) -> Dict[str, Any]:
    """对明确属于MP4相对时钟的时间点，解码一帧并核验实际PTS。

    不能把这里的FFmpeg映射用作HGKS官方VRS->MP4帧映射的替代。
    """
    if source.get("timebase") != "mp4_relative_seconds":
        raise ValueError("ffmpeg_video_requires_mp4_relative_timebase")
    video = _source_path(source["video_path"], root)
    if not video.is_file() or sha256_file(video) != source.get("video_sha256"):
        raise ValueError("video_missing_or_hash_mismatch:%s" % video)
    ffmpeg = _source_path(source["ffmpeg_executable"], root)
    if not ffmpeg.is_file():
        raise FileNotFoundError("ffmpeg_executable_missing:%s" % ffmpeg)
    # Decoding from the start is deliberate: no uncertain seek-based PTS mapping.
    filter_text = "setpts=PTS-STARTPTS,select=gte(t\\,%.6f),showinfo" % selection_time
    cmd = [str(ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "info", "-i", str(video),
           "-vf", filter_text, "-frames:v", "1", "-q:v", "2", "-y", str(target)]
    try:
        process = subprocess.run(cmd, text=True, capture_output=True, shell=False,
                                 timeout=600, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("ffmpeg_frame_decode_timeout") from exc
    if process.returncode != 0:
        raise RuntimeError("ffmpeg_frame_decode_failed:%s" % process.stderr[-600:])
    pts = [float(x) for x in PTS_RE.findall(process.stderr)]
    if not pts:
        raise ValueError("ffmpeg_did_not_report_frame_pts")
    decoded = pts[-1]
    if decoded < selection_time or decoded - selection_time > tolerance_s:
        raise ValueError("decoded_frame_outside_tolerance:%.6f:%.6f" %
                         (selection_time, decoded))
    return {"path": target, "frame_time_s": decoded,
            "sha256": _checked_jpeg(target), "source_mode": "video_ffmpeg"}


def materialize_images(selection_path: Path, sources_path: Path, output_root: Path,
                       tolerance_s: float = 0.25,
                       video_id: str = None) -> Dict[str, Any]:
    """输入：M1选帧Manifest+图像来源（索引或MP4）；输出：JPEG+图像Manifest。

    输出M1_SELECTED_IMAGES.json保留候选时间、实际图像时间、两者误差和SHA。
    可按video_id只导出一个视频；全程使用partial目录，失败时不发布半成品。
    缺源图、哈希改变、时间偏移过大都会失败，不会虚构证据。
    """
    selection_path = Path(selection_path).resolve()
    sources_path = Path(sources_path).resolve()
    output_root = Path(output_root).resolve()
    if output_root.exists():
        raise FileExistsError("images_output_exists:%s" % output_root)
    if (isinstance(tolerance_s, bool) or not isinstance(tolerance_s, (float, int))
            or not math.isfinite(tolerance_s) or not 0 < tolerance_s <= 1):
        raise ValueError("invalid_frame_tolerance")
    selected = read_json(selection_path)
    sources = read_json(sources_path)
    if selected.get("schema_version") != "m1_hgks_v2_selected_timestamps_v1":
        raise ValueError("invalid_hgks_selection_schema")
    if sources.get("schema_version") != SOURCE_SCHEMA:
        raise ValueError("invalid_frame_source_schema")
    mappings = sources.get("videos", {})
    if not isinstance(mappings, dict):
        raise ValueError("frame_sources_videos_must_be_object")
    # A DEV/TEST portable input may contain 23 videos. Do not require JPEGs
    # for unrelated videos when preparing one task for a single video.
    selected_videos = selected["videos"]
    if video_id is not None:
        selected_videos = [row for row in selected_videos
                           if row["video_id"] == video_id]
        if len(selected_videos) != 1:
            raise ValueError("selected_video_id_not_unique_or_missing")
    outputs = []
    # Build into a private staging directory; do not publish partial results.
    staging = output_root.with_name(output_root.name + ".partial")
    if staging.exists():
        raise FileExistsError("images_staging_exists:%s" % staging)
    staging.mkdir(parents=True, exist_ok=False)
    try:
        for video in selected_videos:
            video_id = _safe_video_id(video["video_id"])
            source = mappings.get(video_id)
            if not isinstance(source, dict):
                raise ValueError("frame_source_missing:%s" % video_id)
            mode = source.get("mode")
            if mode not in ("indexed_jpegs", "video_ffmpeg"):
                raise ValueError("unsupported_frame_source_mode:%s" % mode)
            if mode == "indexed_jpegs" and source.get("timebase") not in (
                    "hgks_selection_seconds", "official_mp4_frames"):
                raise ValueError("indexed_jpegs_timebase_required")
            folder = staging / video_id
            folder.mkdir()
            used = set()
            images = []
            for order, item in enumerate(video["selected"], start=1):
                t = _positive_seconds(item["time_s"], "selected_timestamp")
                dst = folder / ("%04d.jpg" % order)
                if mode == "indexed_jpegs":
                    resolved = _from_index(t, source, sources_path.parent,
                                           tolerance_s, used)
                    shutil.copyfile(str(resolved["path"]), str(dst))
                    if _checked_jpeg(dst, resolved["sha256"]) != resolved["sha256"]:
                        raise RuntimeError("jpeg_copy_mismatch")
                else:
                    resolved = _from_video(t, source, sources_path.parent, dst,
                                           tolerance_s)
                images.append({"order": order, "candidate_index": item["candidate_index"],
                               "selected_time_s": t, "timestamp_s": resolved["frame_time_s"],
                               "mapping_error_s": round(resolved["frame_time_s"] - t, 6),
                               "source_timebase": source["timebase"],
                               "path": str((output_root / video_id / dst.name).resolve()),
                               "image_sha256": resolved["sha256"],
                               "source_mode": resolved["source_mode"]})
            outputs.append({"video_id": video_id, "K": len(images), "images": images})
        result = {"schema_version": OUTPUT_SCHEMA, "selected_manifest_sha256":
                  sha256_file(selection_path), "frame_sources_sha256": sha256_file(sources_path),
                  "image_materialized": True, "videos": outputs}
        write_json(staging / "M1_SELECTED_IMAGES.json", result)
        staging.rename(output_root)
        return result
    except Exception:
        shutil.rmtree(str(staging), ignore_errors=True)
        raise
