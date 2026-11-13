"""1101的PC专用Claude任务协议：JPEG+SOP -> 逐帧观察/事件/BT JSON。

先看 render_prompt_pc_d()：为PC设备翻新任务生成提示词，三阶段是
frame_observations -> events -> bt。schema_bundle_pc_d()固定版本与哈希；
validate_bt_pc_d()校验输出结构。与烹饪研究历史D Prompt独立，不改原D。

SOP步骤时间只是上下文，不是视觉证据；PC_D只允许M6B当前支持的
Sequence/Fallback/Selector/Condition/Action，不允许Parallel。
"""
import copy
import json
import math
from typing import Any, Dict, List

from .schema import sha256_obj
from .schema_d import BT_SCHEMA_D

PROMPT_VERSION_PC_D = "CLAUDE_VISION_PC_D_V2_20261113"
SCHEMA_VERSION_PC_D = "CLAUDE_VISION_BT_SCHEMA_PC_D_V1"
# Keep research D byte-identical. The PC task exporter cannot compile Parallel.
BT_SCHEMA_PC_D = copy.deepcopy(BT_SCHEMA_D)
BT_SCHEMA_PC_D["title"] = "ClaudeVisionPCBTOutput"
BT_SCHEMA_PC_D["definitions"]["node"]["properties"]["type"]["enum"] = [
    "Sequence", "Fallback", "Selector", "Condition", "Action"
]

PROMPT_PC_D = """Reconstruct evidence-bounded action events and a candidate behaviour tree
from a PC refurbishment video. Work in the following order: observe every frame,
form small action events, then arrange the events into a task tree.

Video: {video_id}. Segment: {start_s:.3f}s to {end_s:.3f}s.
The following images are in chronological order. Use the Read tool to open ALL
images before answering. File names are relative to the job directory.

FRAME LIST
{frame_lines}

SOP WITH STEP TIMES (source context, NOT a statement of what the video shows)
{sop}

STAGE 1: For each frame, emit frame_observations with exactly one entry per frame:
- hands: visible hand position, hand/object contact or "not visible".
- objects_touched: observed parts, tools, fasteners, cables and devices.
- scene_state: externally visible device state, placement and connections.
- change_since_previous: concrete visible differences (frame 1: "first frame").
Do not claim the internal device state can be seen if no image establishes it.

STAGE 2: Emit fine-grained Action Events. Each Action should represent one
observable manipulation or one clearly identified state-change inference.
Include event_id, order, verb, object, target, before_state, after_state,
frame_indices, evidence_basis, reason and uncertainty.
Evidence categories:
- DIRECT: an image directly shows the manipulation; cite that frame.
- STATE_INFERENCE: before/after frames constrain the action. Cite the bracketing
  frames, explain alternatives, and set uncertainty >= 0.5.
- SOP_HYPOTHESIS: the SOP specifies the action but the images do not establish it.
  Cite no frames, state the SOP step in reason, and set uncertainty >= 0.6.
Do not turn SOP timestamps or prior domain knowledge into DIRECT observations.
Do not invent actions to fill gaps or to match SOP step counts.

STAGE 3: Construct a candidate BT using Sequence, Fallback, Condition and Action.
Every Action must reference one valid event_id, exactly once, in chronological
order. Use a Condition/Fallback only when there is a meaningful, reviewable
predicate; do not invent branches or retries merely because they are possible.
In a Fallback the first child returning SUCCESS skips all later children: write
condition polarity accordingly. Do not use a positive condition to skip actions
that should happen when that condition is true.
When unsure about a condition, prefer a Sequence and state the uncertainty in
related events. This tree is a NON-EXECUTABLE proposal; do not claim robot skill
bindings, runtime postconditions or execution safety.

Return only one JSON object satisfying the OUTPUT SCHEMA. Do not use Markdown.

OUTPUT SCHEMA
{schema}
"""


def render_prompt_pc_d(video_id: str, start_s: float, end_s: float,
                       images: List[Dict[str, Any]], sop: str) -> str:
    """输入：有序图片清单、视频片段秒数、SOP文本；输出：版本化PC_D Prompt。"""
    if not images:
        raise ValueError("PC_D requires real images")
    if not (math.isfinite(start_s) and math.isfinite(end_s)
            and 0 <= start_s < end_s):
        raise ValueError("PC_D invalid segment times")
    lines = "\n".join(
        "{order}. t={timestamp_s:.3f}s file=images/{file}".format(**image)
        for image in images
    )
    schema = json.dumps(BT_SCHEMA_PC_D, ensure_ascii=False, sort_keys=True,
                        separators=(",", ":"))
    return PROMPT_PC_D.format(video_id=video_id, start_s=float(start_s),
                              end_s=float(end_s), frame_lines=lines,
                              sop=sop.strip(), schema=schema)


def schema_bundle_pc_d() -> Dict[str, Any]:
    """输出协议版本、Schema内容哈希和允许的BT节点列表。"""
    return {"prompt_family": "PC_D", "prompt_version": PROMPT_VERSION_PC_D,
            "schema_version": SCHEMA_VERSION_PC_D,
            "schema_sha256": sha256_obj(BT_SCHEMA_PC_D),
            "node_types": BT_SCHEMA_PC_D["definitions"]["node"]["properties"]["type"]["enum"],
            "frame_policy": "D evidence-table-first, PC domain, no Parallel"}


def validate_bt_pc_d(doc: dict, n_images: int = None) -> List[str]:
    """输入：模型JSON和图片数量；输出：错误列表（空列表表示结构通过）。

    复用冻结D的事件格式校验，额外拒绝当前M6B不能导出的Parallel。
    结构通过不等于Condition语义通过，后者仍需人工审核。
    """
    from .schema_d import validate_bt_d

    errors = validate_bt_d(doc, n_images)

    def walk(node: dict, depth: int = 0) -> None:
        if not isinstance(node, dict) or depth > 80:
            errors.append("invalid_or_overdeep_pc_bt_node")
            return
        if node.get("type") not in BT_SCHEMA_PC_D["definitions"]["node"]["properties"]["type"]["enum"]:
            errors.append("unsupported_pc_bt_node:%s" % node.get("type"))
        children = node.get("children", [])
        if not isinstance(children, list):
            errors.append("invalid_pc_bt_children")
            return
        for child in children:
            walk(child, depth + 1)

    if isinstance(doc, dict) and isinstance(doc.get("bt"), dict):
        walk(doc["bt"])
    return errors
