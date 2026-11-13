"""1101侧的薄入口：XPZHU的选中JPEG+SOP -> 不可变PC_D Claude Job。

main()读入--images所给的[{path,timestamp_s}]，调用已有job.create_job()，
输出Job路径。它不启动Claude、不产生Action Events和BT。
真实收费调用、模型身份/回执检查，仍由1101已有run_one.py负责。
这里不重写已有Job/Runner逻辑，避免产生不一致的第二套实现。
"""
import argparse
import json
import re
from pathlib import Path

from claude_vision.job import create_job


def main() -> None:
    """命令入口：解析参数、检查图片清单，再交给已有create_job()。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-root", type=Path, required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--end", type=float, required=True)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--sop", type=Path, required=True)
    parser.add_argument("--model", default="claude-opus-5-5")
    parser.add_argument("--budget-usd", type=float, default=3.0)
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.job_id):
        raise ValueError("unsafe_job_id")
    images = json.loads(args.images.read_text(encoding="utf-8"))
    if not isinstance(images, list) or not images:
        raise ValueError("images_must_be_nonempty_array")
    if args.start >= args.end:
        raise ValueError("segment_start_must_precede_end")
    job_path = create_job(args.job_root, args.job_id, video_id=args.video_id,
                          segment_start_s=args.start, segment_end_s=args.end,
                          images=images, sop_text=args.sop.read_text(encoding="utf-8"),
                          model_alias=args.model, budget_usd=args.budget_usd,
                          timeout_s=args.timeout, prompt_family="PC_D",
                          note="XPZHU HGKS V2 cached input; PC task review candidate")
    print(json.dumps({"status": "JOB_READY_NOT_EXECUTED", "job_dir": str(job_path)},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
