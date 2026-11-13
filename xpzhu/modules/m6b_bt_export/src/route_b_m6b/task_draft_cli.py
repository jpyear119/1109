"""M6B独立命令入口：完整Claude D/PC_D Job -> 可审阅BT XML。

--correction是来源绑定的人工修订提案；--decisions是显式审核决定。
没有审核文件时只输出Draft XML，不会把模型结果称作已批准。
"""
# 命令示例（PowerShell，在完整XPZHU仓库安装后执行）：
#    $XPZHU = 'C:\Project08\11\1109'               # 改成自己的绝对路径
#    $JOB = 'C:\Project08\P05_replay\P05_930_1090_D_hgks_k32_704'
#    $OUT = 'C:\Project08\P05_offline_export_01' # 必须是尚不存在的目录
#    $env:PYTHONPATH = "$XPZHU\modules\m6b_bt_export\src"
#    python -m route_b_m6b.task_draft_cli --job-dir $JOB --output $OUT
#    Get-Content (Join-Path $OUT 'TASK_BT_EXPORT_RESULT.json')
#    Get-Content (Join-Path $OUT 'TASK_REVIEW_TEMPLATE.json')
# 也可用XPZHU唯一工作流入口tools/hgks_task_flow.py export，
# 二者调用的是同一个export_candidate()，不是两套不同编译器。
# 不提供--decisions时只生成Draft XML；不能替人工自动批准任何Condition。

import argparse
import json
from pathlib import Path

from .task_draft import export_candidate


def main() -> None:
    """将CLI参数交给task_draft.export_candidate()，不重复实现编译。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, help="Explicit human review decisions")
    parser.add_argument("--correction", type=Path, help="Versioned human-corrected BT proposal")
    args = parser.parse_args()
    result = export_candidate(args.job_dir, args.output, args.decisions, args.correction)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
