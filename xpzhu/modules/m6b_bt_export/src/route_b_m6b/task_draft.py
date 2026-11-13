"""Task级BT草案编译：已入库Claude Job -> Task IR -> 可审阅XML。

建议先看最下方 export_candidate()，再顺着以下函数向上跳转：
1. _job_evidence()：核验图片、Prompt、Schema、模型回执等来源身份。
2. _validate_events() / _read_tree()：检查事件证据引用及控制树。
3. compile_draft_ir()：保留事件和原树，构造统一Task IR与审核对象。
4. _validate_approval()：只有所有审核对象显式接受，才准输出Reviewed XML。
5. export_candidate()：调用唯一M6B XML编译器并写出候选文件。

结构检查只证明引用与语法自洽，不能证明动作真实、Fallback极性正确、
机器人可运行。模型标注的DIRECT也不是独立人工观察的证明。
本文件不冒充原XPZHU M5/M6的门禁结果，不提供执行级节点。
"""
# 本模块实际输入：一个已完成、通过入库审查的Claude D/PC_D Job目录。
# 本模块实际输出：未审核Task IR和BT_DRAFT_CANDIDATE.xml，以及审查清单。
# PowerShell本地P05回放完整指令见XPZHU/tools/hgks_task_flow.py顶部。
# 其最关键的CLI为：python tools/hgks_task_flow.py export --job-dir $P05 --output $OUT
# 不需要重训HGKS或重新付费调用Claude；这不是完整M1选帧实测。

import json
import hashlib
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from .io_utils import read_json, write_json
from .xml_writer import synthesize_task_draft_xml, generate_node_model_xml
from .validators import validate_bt_xml


IR_SCHEMA = "route_b_task_draft_ir_v1"
ALLOWED_NODES = {"Sequence", "Fallback", "Selector", "Action", "Condition"}
ACTION_MODEL = {"interfaces": [{"interface_id": "route_b_draft_action_v1",
  "bt_node_id": "RouteBActionCandidate", "ports": [
  {"name": "event_ref", "type": "string", "direction": "input", "required": True}]}]}
CONDITION_MODEL = {"interfaces": [{"interface_id": "route_b_draft_condition_v1",
  "bt_node_id": "RouteBConditionCandidate", "ports": [
  {"name": "condition_ref", "type": "string", "direction": "input", "required": True}]}]}


def _sha256_file(path: Path) -> str:
    from hashlib import sha256
    h = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _job_evidence(job_dir: Path) -> Dict[str, Any]:
    """输入：真实完成的Job目录；输出：已核验的请求、逐帧清单、回执和BT。

    不信任单个布尔字段：交叉检查内容哈希、图片字节、提示词及模型身份。
    """
    request = read_json(job_dir / "REQUEST.json")
    manifest = read_json(job_dir / "MANIFEST.json")
    receipt = read_json(job_dir / "RECEIPT.json")
    bt_path = job_dir / "BT_OUTPUT.json"
    bt = read_json(bt_path)

    if (receipt.get("ingested") is not True or receipt.get("blocked_reasons")
            or receipt.get("status") != "OK" or receipt.get("returncode") != 0):
        raise ValueError("claude_job_not_ingested")
    for key in ("manifest_sha256", "prompt_sha256"):
        if request.get(key) != receipt.get(key):
            raise ValueError("job_receipt_%s_mismatch" % key)
    if request.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise ValueError("job_manifest_identity_mismatch")
    # The independent output is only as trustworthy as the immutable request.
    # Verify source files, not merely equality between two editable JSON fields.
    def hash_text(path: Path) -> str:
        # Claude's job hashes Unicode text before writing the file. On Windows
        # the saved file may have CRLF line endings; universal newline reading
        # reproduces the original job.sha256_text() contract.
        return hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()

    if hash_text(job_dir / "PROMPT.md") != request.get("prompt_sha256"):
        raise ValueError("job_prompt_hash_mismatch")
    if hash_text(job_dir / "SOP.md") != request.get("sop_sha256"):
        raise ValueError("job_sop_hash_mismatch")
    schema_path = job_dir / "SCHEMA.json"
    schema = read_json(schema_path)
    schema_digest = hashlib.sha256(json.dumps(schema, ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if schema_digest != request.get("schema", {}).get("schema_sha256"):
        raise ValueError("job_schema_hash_mismatch")
    manifest_digest = hashlib.sha256(json.dumps(manifest.get("images", []),
        ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if manifest_digest != manifest.get("manifest_sha256"):
        raise ValueError("job_manifest_content_hash_mismatch")
    if request.get("k_images") != manifest.get("count") or not manifest.get("images"):
        raise ValueError("job_frame_count_mismatch")
    if (receipt.get("n_events") != len(bt.get("events", []))
            or receipt.get("k_images") != manifest.get("count")
            or not receipt.get("model_id_actual")):
        raise ValueError("job_receipt_content_mismatch")
    if request.get("video_id") != bt.get("video_id"):
        raise ValueError("job_video_id_mismatch")
    for field in ("segment_start_s", "segment_end_s"):
        if abs(float(bt.get(field, -1)) - float(request[field])) > 1:
            raise ValueError("job_segment_mismatch:%s" % field)
    if request.get("prompt_family") not in ("D", "PC_D"):
        raise ValueError("task_export_requires_evidence_table_prompt")
    images = manifest["images"]
    if len(images) != manifest["count"]:
        raise ValueError("manifest_image_length_mismatch")
    for order, frame in enumerate(images, start=1):
        filename = frame.get("file")
        if filename != "%04d.jpg" % order or frame.get("order") != order:
            raise ValueError("manifest_image_order_invalid")
        path = job_dir / "images" / filename
        if (not path.is_file() or _sha256_file(path) != frame.get("sha256")
                or path.stat().st_size != frame.get("bytes")):
            raise ValueError("manifest_image_hash_mismatch:%s" % filename)
    return {"request": request, "manifest": manifest, "receipt": receipt,
            "bt": bt, "output_sha256": _sha256_file(bt_path)}


def _validate_events(bt: Dict[str, Any], n_images: int) -> Dict[str, Dict[str, Any]]:
    """事件JSON -> event_id索引；检查顺序、证据标签和1-based帧引用。"""
    events = bt.get("events")
    if not isinstance(events, list) or not events:
        raise ValueError("bt_events_missing")
    lookup = {}
    for index, event in enumerate(events, start=1):
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", event_id):
            raise ValueError("invalid_event_id")
        if event_id in lookup:
            raise ValueError("duplicate_event_id:%s" % event_id)
        if event.get("order") != index:
            raise ValueError("event_order_must_be_1_to_N")
        basis = event.get("evidence_basis")
        refs = event.get("frame_indices")
        if basis not in {"DIRECT", "STATE_INFERENCE", "SOP_HYPOTHESIS"}:
            raise ValueError("unsupported_evidence_basis:%s" % basis)
        if not isinstance(refs, list) or any(type(x) is not int or x < 1 or x > n_images for x in refs):
            raise ValueError("invalid_frame_refs:%s" % event_id)
        if basis == "SOP_HYPOTHESIS" and refs:
            raise ValueError("sop_hypothesis_cannot_cite_frames")
        if basis != "SOP_HYPOTHESIS" and not refs:
            raise ValueError("visual_evidence_refs_missing")
        if basis == "STATE_INFERENCE" and event.get("uncertainty", 0) < 0.5:
            raise ValueError("state_inference_uncertainty_too_low")
        if basis == "SOP_HYPOTHESIS" and event.get("uncertainty", 0) < 0.6:
            raise ValueError("sop_hypothesis_uncertainty_too_low")
        for key in ("verb", "object", "target", "before_state", "after_state", "reason"):
            if not isinstance(event.get(key), str) or not event[key].strip():
                raise ValueError("event_field_missing:%s:%s" % (event_id, key))
        lookup[event_id] = event
    return lookup


def _read_tree(node: Dict[str, Any], where: str,
               known_events: Dict[str, Dict[str, Any]], seen: List[str],
               reviews: List[Dict[str, str]], depth: int = 0) -> Dict[str, Any]:
    """递归读取模型BT，生成候选树及Condition/Control独立审核目标。"""
    if depth > 80:
        raise ValueError("bt_tree_too_deep")
    if not isinstance(node, dict) or node.get("type") not in ALLOWED_NODES:
        raise ValueError("unsupported_bt_node:%s" % where)
    kind = node["type"]
    if kind == "Action":
        event_id = node.get("event_id")
        if event_id not in known_events:
            raise ValueError("unknown_bt_event_ref:%s" % event_id)
        seen.append(event_id)
        return {"type": "Action", "event_ref": event_id}
    if kind == "Condition":
        statement = node.get("condition")
        if not isinstance(statement, str) or not statement.strip():
            raise ValueError("empty_condition:%s" % where)
        condition_id = "C_" + where.replace("/", "_")
        reviews.append({"target_id": "condition:" + condition_id,
                        "kind": "condition", "description": statement})
        return {"type": "Condition", "condition_ref": condition_id,
                "statement": statement}
    children = node.get("children")
    if not isinstance(children, list) or not children:
        raise ValueError("control_node_without_children:%s" % where)
    # In BehaviorTree.CPP Fallback is the supported equivalent of Selector.
    normalized = "Fallback" if kind == "Selector" else kind
    result = [_read_tree(child, where + "/" + str(i), known_events,
                         seen, reviews, depth + 1) for i, child in enumerate(children)]
    summaries = []
    for child in result:
        if child["type"] == "Action":
            summaries.append("Action(" + child["event_ref"] + ")")
        elif child["type"] == "Condition":
            summaries.append("Condition(" + child["statement"] + ")")
        else:
            summaries.append(child["type"] + "(...)" )
    description = "%s: %s" % (kind, " -> ".join(summaries))
    if normalized == "Fallback":
        description += "; if first child returns SUCCESS, later children are skipped"
    reviews.append({"target_id": "control:" + where, "kind": "control",
                    "description": description})
    return {"type": normalized, "source_type": kind, "children": result}


def compile_draft_ir(job_dir: Path, correction_path: Path = None) -> Dict[str, Any]:
    """输入：已验证Job+可选人工修订；输出：Task IR及审核清单。

    每个Action必须正好出现一次，事件顺序与树顺序必须一致。
    修订以独立文件输入并改变proposal_sha256，旧审核决定自动失效。
    """
    job_dir = Path(job_dir).resolve()
    evidence = _job_evidence(job_dir)
    bt = evidence["bt"]
    correction_sha = None
    corrected_by = None
    if correction_path is not None:
        # A correction never mutates the model result. Revalidate the complete
        # revised event/tree proposal, then request new human decisions.
        correction_path = Path(correction_path).resolve()
        correction = read_json(correction_path)
        if (correction.get("schema_version") != "task_draft_correction_v1" or
                correction.get("source_job_output_sha256") != evidence["output_sha256"] or
                not correction.get("author") or not correction.get("reason")):
            raise ValueError("invalid_task_draft_correction_identity")
        if not isinstance(correction.get("events"), list) or not isinstance(correction.get("bt"), dict):
            raise ValueError("corrected_events_and_bt_required")
        bt = dict(bt, events=correction["events"], bt=correction["bt"])
        correction_sha = _sha256_file(correction_path)
        corrected_by = correction["author"]
    images = evidence["manifest"]["images"]
    events = _validate_events(bt, len(images))
    seen, reviews = [], []
    tree = _read_tree(bt["bt"], "root", events, seen, reviews)
    counts = Counter(seen)
    if set(counts) != set(events) or any(n != 1 for n in counts.values()):
        raise ValueError("bt_action_coverage_not_exactly_once")
    if [events[event_id]["order"] for event_id in seen] != list(range(1, len(events) + 1)):
        raise ValueError("bt_order_conflicts_with_events")
    for event in events.values():
        reviews.append({"target_id": "event:" + event["event_id"],
                        "kind": "event", "description": "%s %s -> %s (%s)" %
                        (event["verb"], event["object"], event["target"], event["evidence_basis"])})
    # Sorting targets stabilizes review files independent of tree traversal details.
    reviews.sort(key=lambda row: row["target_id"])
    proposal_payload = {"source_job_output_sha256": evidence["output_sha256"],
                        "correction_sha256": correction_sha,
                        "events": list(events.values()), "tree": tree}
    proposal_sha = hashlib.sha256(json.dumps(proposal_payload, ensure_ascii=False,
                                              sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {"schema_version": IR_SCHEMA,
            "task_id": evidence["request"]["job_id"],
            "source_video_id": evidence["request"]["video_id"],
            "source_job_dir": str(job_dir),
            "source_job_output_sha256": evidence["output_sha256"],
            "proposal_sha256": proposal_sha,
            "correction_sha256": correction_sha,
            "corrected_by": corrected_by,
            "source_manifest_sha256": evidence["request"]["manifest_sha256"],
            "source_prompt_sha256": evidence["request"]["prompt_sha256"],
            "prompt_family": evidence["request"]["prompt_family"],
            "frame_refs": [{"index": frame["order"], "time_s": frame["timestamp_s"],
                            "image_sha256": frame["sha256"]} for frame in images],
            "events": list(events.values()), "tree": tree, "review_targets": reviews,
            "human_review_performed": False, "non_executable": True,
            "execution_safe": False, "limitations": [
                "Model-assigned evidence_basis is not independent observation proof.",
                "SOP statements and conditional control logic require human review.",
                "The XML contains generic proposal nodes, not executable robot skills."]}


def _validate_approval(ir: Dict[str, Any], decisions_path: Path) -> Dict[str, Any]:
    """输入：全部Event、Condition、Control人工决定；输出：审核通过记录。

    只验证审核文件是否完整且与当前提案匹配，不替审核者判断逻辑正确。
    """
    decisions = read_json(decisions_path)
    if decisions.get("schema_version") != "task_draft_review_decisions_v1":
        raise ValueError("task_review_schema_mismatch")
    if (decisions.get("source_job_output_sha256") != ir["source_job_output_sha256"] or
            decisions.get("proposal_sha256") != ir["proposal_sha256"]):
        raise ValueError("task_review_source_or_proposal_hash_mismatch")
    expected = {t["target_id"] for t in ir["review_targets"]}
    entries = decisions.get("decisions")
    if not isinstance(entries, list) or {d.get("target_id") for d in entries} != expected or len(entries) != len(expected):
        raise ValueError("task_review_targets_not_exactly_covered")
    for item in entries:
        if (item.get("decision") != "accept" or not item.get("reviewer_id") or
                not item.get("reviewed_at") or not str(item.get("comment", "")).strip()):
            raise ValueError("task_review_not_fully_accepted")
    return {"status": "APPROVED_FOR_REVIEWED_XML", "review_sha256": _sha256_file(decisions_path),
            "reviewed_target_count": len(entries)}


def export_candidate(job_dir: Path, output_root: Path,
                     decisions_path: Path = None,
                     correction_path: Path = None) -> Dict[str, Any]:
    """输入：Job、目标目录及可选审核/修订文件；输出：Task IR和XML。

    默认只产生 BT_DRAFT_CANDIDATE.xml；当审核决定全部通过时才额外
    写BT_REVIEWED_CANDIDATE.xml。两者始终non_executable=True。
    文件写入partial目录后原子改名，避免审核者看到不完整产物。
    """
    output_root = Path(output_root).resolve()
    if output_root.exists():
        raise FileExistsError("bt_candidate_output_exists:%s" % output_root)
    ir = compile_draft_ir(job_dir, correction_path)
    xml = synthesize_task_draft_xml(ir, ACTION_MODEL, CONDITION_MODEL)
    checked = validate_bt_xml(xml, ACTION_MODEL, CONDITION_MODEL)
    if checked["status"] != "PASS":
        raise ValueError("draft_xml_structural_validation_failed:%s" % checked["issues"])
    approval = _validate_approval(ir, decisions_path) if decisions_path else None
    staging = output_root.with_name(output_root.name + ".partial")
    if staging.exists():
        raise FileExistsError("bt_candidate_staging_exists")
    staging.mkdir(parents=True, exist_ok=False)
    try:
        write_json(staging / "TASK_DRAFT_IR.json", ir)
        (staging / "BT_DRAFT_CANDIDATE.xml").write_text(xml, encoding="utf-8")
        (staging / "NODE_MODELS.xml").write_text(
            generate_node_model_xml(ACTION_MODEL, CONDITION_MODEL), encoding="utf-8")
        write_json(staging / "BT_XML_VALIDATION.json", checked)
        write_json(staging / "TASK_REVIEW_TEMPLATE.json", {
            "schema_version": "task_draft_review_decisions_v1",
            "source_job_output_sha256": ir["source_job_output_sha256"],
            "proposal_sha256": ir["proposal_sha256"],
            "decisions": [{"target_id": row["target_id"], "kind": row["kind"],
                           "description": row["description"], "decision": "",
                           "reviewer_id": "", "reviewed_at": "", "comment": ""}
                          for row in ir["review_targets"]],
        })
        if approval:
            (staging / "BT_REVIEWED_CANDIDATE.xml").write_text(xml, encoding="utf-8")
            write_json(staging / "TASK_REVIEW_RESULT.json", approval)
        result = {"status": "PASS", "draft_xml_generated": True,
                  "reviewed_xml_generated": approval is not None,
                  "action_count": len(ir["events"]),
                  "review_target_count": len(ir["review_targets"]),
                  "non_executable": True, "execution_safe": False,
                  "source_job_output_sha256": ir["source_job_output_sha256"],
                  "proposal_sha256": ir["proposal_sha256"],
                  "correction_applied": correction_path is not None}
        write_json(staging / "TASK_BT_EXPORT_RESULT.json", result)
        staging.rename(output_root)
        return result
    except Exception:
        shutil.rmtree(str(staging), ignore_errors=True)
        raise
