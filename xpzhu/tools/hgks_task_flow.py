"""XPZHU 项目入口：把 HGKS 选帧结果逐步转换为待审阅的 Task-level BT。

推荐的源码阅读顺序（VS Code 可按函数名跳转）：
1. select()  -> M1Service.run() -> hgks_v2_backend.run_cached()
2. images()  -> hgks_images.materialize_images()
3. prepare() -> 1101/claude_vision/xpzhu_bridge.py -> job.create_job()
4. export   -> task_draft.export_candidate() -> M6B xml_writer

每一步都有明确输入和输出，不依赖上一条命令的隐式进程状态；各阶段产物
保存在同一个 runtime_runs/<run_id> 目录中。prepare 只建 Claude Job，
不会调用付费模型；生成 BT_OUTPUT.json 的真实 Claude 调用不在此文件中。
这条路径当前只生成不可执行的候选 XML，不包含 Theme B 机器人执行。
"""
# ===== 先跑P05：PowerShell命令（离线，零Claude费用，零HGKS重新推断） =====
# 1. 在VS Code终端使用PowerShell；把下面三个路径改成自己电脑的实际位置。
#    $XPZHU = 'C:\Project08\11\1109'      # 安装了本代码的XPZHU Git工作树
#    $P05_ZIP = 'C:\Project08\P05_930_1090_D_hgks_k32_704.zip'
#    $P05_DIR = 'C:\Project08\P05_replay'
# 2. 解压历史真实D实验Job，注意ZIP本身含一级同名目录。
#    Expand-Archive -LiteralPath $P05_ZIP -DestinationPath $P05_DIR
#    $P05 = Join-Path $P05_DIR 'P05_930_1090_D_hgks_k32_704'
#    Test-Path (Join-Path $P05 'BT_OUTPUT.json')  # 必须返回True
#    Test-Path (Join-Path $P05 'RECEIPT.json')    # 必须返回True
# 3. 从已完成的Job重建BT候选（选择一个不存在的输出目录）。
#    $OUT = Join-Path $XPZHU 'runtime_runs\P05_offline_bt_review_01'
#    python "$XPZHU\tools\hgks_task_flow.py" export --job-dir $P05 --output $OUT
#    Get-Content (Join-Path $OUT 'TASK_BT_EXPORT_RESULT.json')
#    Get-Content (Join-Path $OUT 'BT_XML_VALIDATION.json')
# 4. 运行P05专项测试，自动校验32张图、27个Action、37个审核目标、无执行批准。
#    $env:P05_JOB_DIR = $P05
#    $env:PYTHONPATH = "$XPZHU\modules\m1\src;$XPZHU\modules\m6b_bt_export\src;$XPZHU\src"
#    python -m pytest -q "$XPZHU\tests\integration\test_hgks_p05_replay.py"
#
# 预期结果：status=PASS、action_count=27、review_target_count=37、
# reviewed_xml_generated=false、execution_safe=false。不要人工把review改成true。
# 本P05是已有Job的离线重放，不能用来声称M1正式模型刚刚重新执行。
# 若OUTPUT已存在，程序会拒绝覆盖：改用新目录名，保留上一次的审查证据。
#
# ===== 之后做真实本地全链路：仅在有相应数据时依次运行 =====
# 先按 tools/install_to_repos.py 顶部注释安装，再配置以下真实路径：
# ① 选帧：
#    python "$XPZHU\tools\hgks_task_flow.py" select --config "$XPZHU\config\templates\hgks_v2_cached.example.json"
#    # 输出包含run_id，记录后供②③使用；请先修改JSON模板的真实路径。
# ② 图片映射（frame-sources需要真实帧来源、SHA及正确时间基）：
#    $RUN_ID = 'REPLACE_WITH_RUN_ID'
#    $VIDEO_ID = 'REPLACE_WITH_FULL_VIDEO_ID'
#    $SOURCES_JSON = 'C:\Project08\your_frame_sources.json'
#    python "$XPZHU\tools\hgks_task_flow.py" images --run-id $RUN_ID --video-id $VIDEO_ID --frame-sources $SOURCES_JSON --tolerance-s 0.25
# ③ PC_D Claude Job准备（不付费，只生成Job和固定Prompt）：
#    $HGKS_PYTHON = 'C:\Project08\HKS_OBJECT_BOUNDARY_EXPERIMENT_20261022\venv_lite\Scripts\python.exe'
#    $SOP_JSON = 'C:\Project08\your_pc_sop_steps.json'
#    $START_S = 0.0  # 按真实SOP任务段修改
#    $END_S = 30.0
#    $JOB_ID = 'PC_demo_segment_01'  # 每段不同；已有同名Job不会覆盖
#    python "$XPZHU\tools\hgks_task_flow.py" prepare --run-id $RUN_ID --video-id $VIDEO_ID --claude-root 'C:\Project08\1101' --python-executable $HGKS_PYTHON --sop $SOP_JSON --start $START_S --end $END_S --job-id $JOB_ID
# ④ 只有已完成真实Claude调用并经过Job入库验证后，才能运行上面的export。
#    关于显式付费授权，查看1101\claude_vision\run_one.py --help。
# 注意：①默认处理完整正式DEV/TEST portable，而P05历史K32和正式ceil(T/30)
# 预算并不相同，不能拿①输出冒充复现历史P05选帧实验。
# =============================================================================

import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modules" / "m1" / "src"))
sys.path.insert(0, str(ROOT / "modules" / "m6b_bt_export" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from route_b_m1.hgks_images import materialize_images  # noqa: E402
from route_b_m1.io_utils import read_json, sha256_file, write_json  # noqa: E402
from route_b_m6b.task_draft import export_candidate  # noqa: E402
from route_b_pipeline.sop_steps import render_sop_steps  # noqa: E402


def _run_root(run_id: str) -> Path:
    """找到且仅允许访问 XPZHU/runtime_runs 下的现有 Run，拒绝路径穿越。"""
    root = (ROOT / "runtime_runs" / run_id).resolve()
    if root.parent != (ROOT / "runtime_runs").resolve() or not (root / "RUN_MANIFEST.json").is_file():
        raise ValueError("invalid_or_missing_run_id")
    return root


def select(config_path: Path) -> dict:
    """输入：HGKS预处理包、模型和Python路径配置；输出：Run ID及选中时间戳。

    真正的141维特征构造、HGB预测和时间分散选择只在1020/predict.py，
    这里没有第二份算法实现。必须提供正式DEV/TEST协议的预处理包。
    """
    from route_b_m1.service import M1Service

    config = read_json(config_path)
    m1 = M1Service(ROOT)
    created = m1.create_hgks_cached_run(config)
    return m1.run(created["run_id"], "hgks_v2_cached") | {"run_id": created["run_id"]}


def images(run_id: str, sources: Path, tolerance: float,
           video_id: str = None) -> dict:
    """输入：已选时间戳及带时间基的图像来源；输出：真实JPEG及其SHA256。

    选中时间不是物理视频帧索引，不能跳过时间基检查直接送给Claude。
    """
    run_root = _run_root(run_id)
    result = materialize_images(run_root / "m1" / "HGKS_SELECTED_TIMESTAMPS.json",
                                sources, run_root / "m1" / "materialized_images",
                                tolerance, video_id=video_id)
    return {"status": "PASS", "run_id": run_id,
            "image_manifest_path": str(run_root / "m1" / "materialized_images"
                                       / "M1_SELECTED_IMAGES.json"),
            "image_count": sum(v["K"] for v in result["videos"])}


def prepare(run_id: str, video_id: str, claude_root: Path, python_executable: Path,
            sop: Path, start: float, end: float, job_id: str,
            model: str, budget: float, timeout: float) -> dict:
    """输入：某视频任务段、该段JPEG和SOP时间；输出：不可变Claude Job目录。

    start/end 是视频内秒数；只选该段中的图，不强迫整段K张图都入Job。
    每段使用不同 job_id，文件名也包含 job_id，避免同一视频多段相互覆盖。
    这里不运行Claude，返回JOB_READY_NOT_EXECUTED并不是已生成BT。
    """
    run_root = _run_root(run_id)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", job_id):
        raise ValueError("unsafe_job_id")
    image_manifest = read_json(run_root / "m1" / "materialized_images" / "M1_SELECTED_IMAGES.json")
    videos = [v for v in image_manifest["videos"] if v["video_id"] == video_id]
    if len(videos) != 1:
        raise ValueError("selected_video_id_not_unique")
    if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end):
        raise ValueError("invalid_task_segment")
    # M1 normally selects across the entire video; task jobs may cover only
    # one SOP step or a shorter segment. Do not reject unrelated M1 frames.
    frames = [row for row in videos[0]["images"]
              if start <= float(row["timestamp_s"]) <= end]
    if not frames:
        raise ValueError("no_selected_images_in_task_segment")
    for row in frames:
        path = Path(row["path"])
        if not path.is_file() or sha256_file(path) != row["image_sha256"]:
            raise ValueError("selected_image_missing_or_changed")
    stamps = [float(row["timestamp_s"]) for row in frames]
    if any(not math.isfinite(t) for t in stamps) or stamps != sorted(stamps):
        raise ValueError("invalid_or_unsorted_image_timestamps")
    images_list = [{"path": row["path"], "timestamp_s": row["timestamp_s"]} for row in frames]
    # 一个视频可以分多个SOP段建单：以job_id隔离输入，防止第二段覆盖第一段。
    input_list = run_root / "m1" / ("CLAUDE_IMAGES_%s.json" % job_id)
    rendered_sop = run_root / "m1" / ("TASK_SOP_%s.md" % job_id)
    sop_provenance = run_root / "m1" / ("TASK_SOP_%s_PROVENANCE.json" % job_id)
    if any(path.exists() for path in (input_list, rendered_sop, sop_provenance)):
        raise FileExistsError("task_preparation_artifacts_already_exist:%s" % job_id)
    claude_root = Path(claude_root).resolve()
    launcher = claude_root / "tools" / "run_hgks.py"
    bridge = claude_root / "claude_vision" / "xpzhu_bridge.py"
    if not launcher.is_file() or not bridge.is_file():
        raise FileNotFoundError("hgks_claude_bridge_not_installed")
    sop_input = render_sop_steps(Path(sop), video_id, start, end)
    write_json(input_list, images_list)
    rendered_sop.write_text(sop_input["sop_text"], encoding="utf-8")
    write_json(sop_provenance, {
        "source_path": str(Path(sop).resolve()),
        "source_sha256": sop_input["source_sha256"],
        "included_step_count": sop_input["included_step_count"],
    })
    job_root = run_root / "m2_task_jobs"
    # 使用1101已有的建单API以保留图片、Prompt、Schema及模型身份的回执。
    # 真实收费调用由run_one.py显式授权，本命令不执行它。
    command = [str(Path(python_executable).resolve()), "-B", str(launcher),
               "claude_vision/xpzhu_bridge.py", "--job-root", str(job_root),
               "--job-id", job_id, "--video-id", video_id,
               "--start", str(start), "--end", str(end), "--images", str(input_list),
               "--sop", str(rendered_sop), "--model", model,
               "--budget-usd", str(budget), "--timeout", str(timeout)]
    result = subprocess.run(command, cwd=str(claude_root), capture_output=True,
                            text=True, shell=False, timeout=180, check=False)
    if result.returncode:
        raise RuntimeError("claude_job_preparation_failed:%s" % result.stderr[-800:])
    return {"status": "JOB_READY_NOT_EXECUTED", "job_dir": str(job_root / job_id),
            "frame_count": len(frames), "result": result.stdout[-1800:]}


def main() -> None:
    """CLI唯一入口：四个子命令对应四次清楚、可独立检查的阶段输出。"""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="stage", required=True)
    p = commands.add_parser("select", help="Run frozen HGKS from a preprocessed bundle")
    p.add_argument("--config", type=Path, required=True)
    p = commands.add_parser("images", help="Resolve selected times to real JPEGs")
    p.add_argument("--run-id", required=True)
    p.add_argument("--frame-sources", type=Path, required=True)
    p.add_argument("--video-id", help="Materialize only this video from a DEV/TEST bundle")
    p.add_argument("--tolerance-s", type=float, default=0.25)
    p = commands.add_parser("prepare", help="Prepare PC_D job; no paid call")
    for name in ("run-id", "video-id", "job-id"):
        p.add_argument("--" + name, required=True)
    for name in ("claude-root", "python-executable", "sop"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--start", type=float, required=True)
    p.add_argument("--end", type=float, required=True)
    p.add_argument("--model", default="claude-opus-5-5")
    p.add_argument("--budget-usd", type=float, default=3.0)
    p.add_argument("--timeout", type=float, default=900.0)
    p = commands.add_parser("export", help="Compile D/PC_D BT JSON to M6B XML candidate")
    p.add_argument("--job-dir", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--decisions", type=Path)
    p.add_argument("--correction", type=Path)
    args = parser.parse_args()
    if args.stage == "select":
        output = select(args.config)
    elif args.stage == "images":
        output = images(args.run_id, args.frame_sources, args.tolerance_s, args.video_id)
    elif args.stage == "prepare":
        output = prepare(args.run_id, args.video_id, args.claude_root,
                         args.python_executable, args.sop, args.start, args.end,
                         args.job_id, args.model, args.budget_usd, args.timeout)
    else:
        output = export_candidate(args.job_dir, args.output, args.decisions, args.correction)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
