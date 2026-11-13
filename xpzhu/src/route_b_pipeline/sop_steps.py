"""PC SOP步骤与时间输入：步骤JSON -> 指定任务段的Prompt上下文。

render_sop_steps()输入视频ID和[start_s, end_s]，只返回与该段重叠的
SOP步骤、其时间来源和原始文件哈希。错误步骤、重名ID和无重叠都会拒绝。
注意SOP是规范/说明，不是视频里动作真实发生的证据；不能据此升级DIRECT。
"""
import math
from pathlib import Path
from typing import Any, Dict

from route_b_m1.io_utils import read_json, sha256_file


def _seconds(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError("invalid_sop_%s" % label)
    n = float(value)
    if not math.isfinite(n) or n < 0:
        raise ValueError("invalid_sop_%s" % label)
    return n


def render_sop_steps(path: Path, video_id: str, start_s: float,
                     end_s: float) -> Dict[str, str]:
    """输入：SOP时间JSON与任务时间段；输出：sop_text、源SHA及步骤数。

    用重叠规则选段，保留time_source；不根据SOP填充模型观察结果。
    """
    path = Path(path).resolve()
    data = read_json(path)
    if data.get("schema_version") != "pc_task_sop_steps_v1":
        raise ValueError("unsupported_pc_sop_schema")
    if data.get("video_id") != video_id:
        raise ValueError("sop_video_id_mismatch")
    rows = data.get("steps", [])
    if not isinstance(rows, list) or not rows:
        raise ValueError("sop_steps_empty")
    seen = set()
    scoped = []
    for row in rows:
        step_id = row.get("step_id")
        if not isinstance(step_id, str) or not step_id.strip() or step_id in seen:
            raise ValueError("invalid_or_duplicate_sop_step_id")
        seen.add(step_id)
        a = _seconds(row.get("start_s"), "step_start")
        b = _seconds(row.get("end_s"), "step_end")
        if not a < b:
            raise ValueError("sop_step_end_must_follow_start")
        label = row.get("text")
        if not isinstance(label, str) or not label.strip():
            raise ValueError("sop_step_text_required")
        source = row.get("time_source")
        if source not in ("sop_document", "video_annotation", "manual_estimate"):
            raise ValueError("sop_step_time_source_required")
        if b <= start_s or a >= end_s:
            continue
        scoped.append((a, b, step_id, label.strip(), source))
    if not scoped:
        raise ValueError("no_sop_step_overlaps_segment")
    lines = ["PC TASK SOP STEP TIMES — instructions, not evidence of action execution"]
    for a, b, sid, label, source in sorted(scoped):
        lines.append("[%0.3fs – %0.3fs] %s: %s (time_source=%s)" %
                     (a, b, sid, label, source))
    return {"sop_text": "\n".join(lines) + "\n",
            "source_sha256": sha256_file(path), "included_step_count": len(scoped)}
