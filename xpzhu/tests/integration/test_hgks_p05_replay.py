r"""可选真实P05回放：直接复用已付费完成的D Job，禁止伪造/重新生成模型输出。

PowerShell运行指令（见tools/hgks_task_flow.py顶部完整解压方法）：
    $XPZHU = 'C:\Project08\11\1109'  # change to actual checkout
    $env:P05_JOB_DIR = 'C:\Project08\P05_replay\P05_930_1090_D_hgks_k32_704'
    $env:PYTHONPATH = "$XPZHU\modules\m1\src;$XPZHU\modules\m6b_bt_export\src;$XPZHU\src"
    python -m pytest -q "$XPZHU\tests\integration\test_hgks_p05_replay.py"

若未设置P05_JOB_DIR会SKIP，不会偷偷创建模拟Job冒充真实实验。
该测试只验证P05已完成Job到XML导出；不会运行M1冻结模型或付费Claude。
"""
import json
import os
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from PIL import Image

from route_b_m6b.task_draft import export_candidate


@pytest.fixture
def p05_job():
    raw = os.environ.get("P05_JOB_DIR")
    if not raw:
        pytest.skip("P05_JOB_DIR未设置，真实P05实验包未指定")
    job = Path(raw).expanduser().resolve()
    if not (job / "BT_OUTPUT.json").is_file():
        pytest.fail("P05_JOB_DIR应指向解压后的真实Job目录，不是ZIP文件")
    request = json.loads((job / "REQUEST.json").read_text(encoding="utf-8"))
    if request.get("job_id") != "P05_930_1090_D_hgks_k32_704":
        pytest.fail("指定的不是历史P05 D K32 Job")
    return job


def test_p05_image_manifest_contains_32_decodable_source_frames(p05_job):
    manifest = json.loads((p05_job / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["count"] == 32
    assert len(manifest["images"]) == 32
    for row in manifest["images"]:
        image_path = p05_job / "images" / row["file"]
        with Image.open(image_path) as image:
            image.load()  # 校验真实JPEG解码，不只检查文件头
            assert image.format == "JPEG"
            assert image.size == (row["width"], row["height"])


def test_p05_completed_d_job_exports_draft_only(p05_job, tmp_path):
    original = (p05_job / "BT_OUTPUT.json").read_bytes()
    out = tmp_path / "p05_export"
    result = export_candidate(p05_job, out)
    assert result["status"] == "PASS"
    assert result["action_count"] == 27
    assert result["review_target_count"] == 37
    assert result["reviewed_xml_generated"] is False
    assert result["non_executable"] is True
    assert result["execution_safe"] is False
    assert (out / "BT_DRAFT_CANDIDATE.xml").is_file()
    assert not (out / "BT_REVIEWED_CANDIDATE.xml").exists()
    assert json.loads((out / "BT_XML_VALIDATION.json").read_text())["status"] == "PASS"
    tree = ET.parse(out / "BT_DRAFT_CANDIDATE.xml").getroot()
    action_refs = [el.attrib["event_ref"] for el in tree.iter("Action")]
    assert len(action_refs) == 27
    assert len(set(action_refs)) == 27
    # 输入Job必须保持字节不变，避免审查过程覆盖历史实验事实。
    assert (p05_job / "BT_OUTPUT.json").read_bytes() == original
