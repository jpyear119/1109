"""V3安装助手：只负责把已审阅源码安全合并进两个本地Git仓库。

它不是视频处理或算法入口；现场讲算法请打开 xpzhu/tools/hgks_task_flow.py。
默认只生成补丁并运行git apply --check，不修改任何源码。
显式--apply时先验证两个仓库和补丁，工作树不干净则拒绝应用。
保留现有CRLF/LF换行，以免Git补丁在Windows出现不必要的整文件差异。
"""
# 本地安装PowerShell示例（默认只生成并检查补丁，不修改仓库）：
#    $BUNDLE = 'C:\Project08\11\1109_hgks_v2_p05_local_v4' # 解压本ZIP的目录
#    $XPZHU  = 'C:\Project08\11\1109'                   # XPZHU Git checkout
#    $HGKS   = 'C:\Project08\1101'                    # HGKS开发Git checkout
#    $PATCH  = 'C:\Project08\hgks_v4_review_patches'  # 必须在两仓库外
#    python "$BUNDLE\tools\install_to_repos.py" --xpzhu-root $XPZHU --hgks-root $HGKS --patch-output $PATCH
#    Get-Content "$PATCH\xpzhu.patch" -TotalCount 50
#    Get-Content "$PATCH\hgks-v2-1101.patch" -TotalCount 50
# 仅当两个仓库HEAD符合预期且无未提交改动，审阅补丁后才显式加 --apply。
# 若HEAD不同，不能盲目使用--allow-different-head：先确认仓库已有的改动。
# 这是安装工具，不是算法执行入口。算法执行请看XPZHU/tools/hgks_task_flow.py。

import argparse
import difflib
import subprocess
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1]
EXPECTED = {
    "xpzhu": "9c90fb98aa18ea9411c5f42ab3ff1f625ab51594",
    "hgks-v2-1101": "d8c48df2b1efc87d1fcdf03487d26a9a32c99523",
}


def replace_once(text: str, needle: str, replacement: str, name: str) -> str:
    count = text.count(needle)
    if count != 1:
        raise ValueError("anchor_mismatch:%s:%s" % (name, count))
    return text.replace(needle, replacement, 1)


def modify_xpzhu(relative: str, value: str) -> str:
    if relative == "modules/m1/src/route_b_m1/workspace.py":
        if "def create_cached_run(" in value:
            raise ValueError("cached_run_already_present")
        return value.rstrip() + '''\n\n\ndef create_cached_run(project_root: Path, input_path: Path,
                      model_sha256: str) -> Dict[str, Any]:
    """输入：预处理包与模型身份；输出：不要求上传视频的XPZHU Run。

    Run记录源SHA并在后续执行时复核，避免替换文件后继续沿用旧结果。
    """
    input_path = input_path.resolve()
    input_digest = sha256_file(input_path)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_id = safe_id("%s_hgks_%s_%s" % (
        timestamp, input_digest[:12], uuid.uuid4().hex[:10]), "run")
    run_root = project_root / "runtime_runs" / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    for name in ["input", "config", "logs", "m1", "m2_dataset",
                 "stage_modules", "artifacts"]:
        (run_root / name).mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "route_b_local_run_manifest_v1",
        "run_id": run_id,
        "mode": "hgks_v2_cached",
        "input_kind": "hgks_preprocessed_candidate_pool",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_input_sha256": input_digest,
        "source_model_sha256": model_sha256,
        "materialized_video_path": None,
        "stage_status": {stage: "NOT_STARTED" for stage in
                         ("m1", "m2", "m3", "m4", "m5", "m6", "m6b")},
        "formal_semantic_acceptance": False,
        "executable_bt_generated": False,
    }
    write_json(run_root / "RUN_MANIFEST.json", manifest)
    return {"run_id": run_id, "run_root": str(run_root), "manifest": manifest}
'''
    if relative == "modules/m1/src/route_b_m1/service.py":
        value = replace_once(value,
            'from .workspace import create_run\n',
            'from .workspace import create_run, create_cached_run\n'
            'from .hgks_v2_backend import preflight as hgks_preflight, run_cached as run_hgks_cached\n',
            relative)
        value = replace_once(value,
            '    def doctor(self) -> Dict[str, Any]:\n',
            '''    def create_hgks_cached_run(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """输入：HGKS配置；输出：已绑定模型/输入哈希的Run。

        先preflight，再写不可变Run配置；本步骤不会运行选帧。
        """
        checked = hgks_preflight(config)
        created = create_cached_run(
            self.project_root, Path(checked["input_bundle"]), checked["model_sha256"])
        write_json(Path(created["run_root"]) / "config" / "HGKS_V2_CACHED.json", config)
        return {"status": "PASS", "preflight": checked, **created}

    def doctor(self) -> Dict[str, Any]:
''', relative)
        value = replace_once(value,
            '        video = run_root / manifest["materialized_video_path"]\n        if mode == "mock":\n',
            '''        # HGKS缓存输入没有materialized_video_path：必须在旧M1视频路径前分支。
        if mode == "hgks_v2_cached":
            if manifest.get("mode") != mode:
                raise ValueError("run_mode_mismatch")
            try:
                config_path = run_root / "config" / "HGKS_V2_CACHED.json"
                cached_config = read_json(config_path)
                checked = hgks_preflight(cached_config)
                if (checked["input_sha256"] != manifest["source_input_sha256"] or
                        checked["model_sha256"] != manifest["source_model_sha256"]):
                    raise RuntimeError("cached_hgks_input_or_model_changed")
                result = run_hgks_cached(run_root, cached_config, preflight_only)
            except Exception:
                manifest["stage_status"]["m1"] = "FAIL"
                write_json(run_root / "RUN_MANIFEST.json", manifest)
                raise
            manifest["stage_status"]["m1"] = (
                "PREFLIGHT_PASS" if preflight_only else "PASS")
            write_json(run_root / "RUN_MANIFEST.json", manifest)
            write_json(run_root / "m1" / "M1_RUN_RESULT.json", result)
            return result
        video = run_root / manifest["materialized_video_path"]
        if mode == "mock":
''', relative)
        return value
    if relative == "apps/local_ui/controller.py":
        value = replace_once(value,
            '    def bundled_m1_example_status(self) -> Dict[str, Any]:\n',
            '''    def create_hgks_cached_run(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """公司Controller入口：用预处理候选池建立Run，不走视频上传流程。"""
        created = self.m1.create_hgks_cached_run(config)
        load_company_config(self._run_root(created["run_id"]))
        return created

    def bundled_m1_example_status(self) -> Dict[str, Any]:
''', relative)
        anchor = '''        run_root = self._run_root(run_id)
        config = load_company_config(run_root)
        if object_roles is not None:
'''
        value = replace_once(value, anchor,
            '''        run_root = self._run_root(run_id)
        if mode == "hgks_v2_cached":
            return self.m1.run(run_id, mode, preflight_only=preflight_only)
        config = load_company_config(run_root)
        if object_roles is not None:
''', relative)
        return value
    if relative == "modules/m6b_bt_export/src/route_b_m6b/xml_writer.py":
        if "def synthesize_task_draft_xml(" in value:
            raise ValueError("task_draft_xml_writer_already_present")
        addition = (BUNDLE / "patches" / "xml_writer_addition.pyfrag").read_text(encoding="utf-8")
        return value.rstrip() + "\n" + addition
    raise ValueError("unexpected_xpzhu_modification:" + relative)


def modify_hgks(relative: str, value: str) -> str:
    if relative == "claude_vision/schema_v2.py":
        value = replace_once(value,
            'PROMPT_FAMILIES = ("V3", "B", "C", "D")',
            'PROMPT_FAMILIES = ("V3", "B", "C", "D", "PC_D")', relative)
        value = replace_once(value,
            '''    if family == "D":
        from .schema_d import PROMPT_VERSION_D

        return PROMPT_VERSION_D
''',
            '''    if family == "D":
        from .schema_d import PROMPT_VERSION_D

        return PROMPT_VERSION_D
    if family == "PC_D":
        from .schema_pc import PROMPT_VERSION_PC_D

        return PROMPT_VERSION_PC_D
''', relative)
        value = replace_once(value,
            '''    if family == "D":
        from .schema_d import render_prompt_d

        return render_prompt_d(video_id, start_s, end_s, images, sop)
''',
            '''    if family == "D":
        from .schema_d import render_prompt_d

        return render_prompt_d(video_id, start_s, end_s, images, sop)
    if family == "PC_D":
        from .schema_pc import render_prompt_pc_d

        return render_prompt_pc_d(video_id, start_s, end_s, images, sop)
''', relative)
        value = replace_once(value,
            '''    if family == "D":
        from .schema_d import schema_bundle_d

        return schema_bundle_d()
''',
            '''    if family == "D":
        from .schema_d import schema_bundle_d

        return schema_bundle_d()
    if family == "PC_D":
        from .schema_pc import schema_bundle_pc_d

        return schema_bundle_pc_d()
''', relative)
        value = replace_once(value,
            '''    if family == "D":
        from .schema_d import validate_bt_d

        return validate_bt_d(doc, n_images)
''',
            '''    if family == "D":
        from .schema_d import validate_bt_d

        return validate_bt_d(doc, n_images)
    if family == "PC_D":
        from .schema_pc import validate_bt_pc_d

        return validate_bt_pc_d(doc, n_images)
''', relative)
        return value
    if relative == "claude_vision/job.py":
        value = replace_once(value,
            '''    elif prompt_family == "D":
        from . import schema_d

        _schema_obj = schema_d.BT_SCHEMA_D
''',
            '''    elif prompt_family == "D":
        from . import schema_d

        _schema_obj = schema_d.BT_SCHEMA_D
    elif prompt_family == "PC_D":
        from . import schema_pc

        _schema_obj = schema_pc.BT_SCHEMA_PC_D
''', relative)
        return value
    raise ValueError("unexpected_hgks_modification:" + relative)


MODIFIED = {
    "xpzhu": ["modules/m1/src/route_b_m1/workspace.py",
              "modules/m1/src/route_b_m1/service.py",
              "apps/local_ui/controller.py",
              "modules/m6b_bt_export/src/route_b_m6b/xml_writer.py"],
    "hgks-v2-1101": ["claude_vision/schema_v2.py", "claude_vision/job.py"],
}


def make_patch(repo: str, root: Path) -> str:
    items = {}
    # Additive files from the bundled relative repository tree.
    overlay = BUNDLE / repo
    for path in sorted(overlay.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            relative = path.relative_to(overlay).as_posix()
            if (root / relative).exists():
                raise ValueError("new_file_already_exists:%s" % relative)
            items[relative] = ("", path.read_text(encoding="utf-8"))
    for relative in MODIFIED[repo]:
        # GitHub's HGKS claude_vision/job.py is CRLF in the actual tracked
        # blob. Preserve its original bytes in the patch context, or git apply
        # can fail on a real checkout even if the LF-only synthetic test passes.
        old = (root / relative).read_bytes().decode("utf-8")
        crlf = old.count("\r\n")
        if crlf and crlf != old.count("\n"):
            raise ValueError("mixed_line_endings:%s" % relative)
        normalized = old.replace("\r\n", "\n")
        updated = (modify_xpzhu(relative, normalized)
                   if repo == "xpzhu" else modify_hgks(relative, normalized))
        new = updated.replace("\n", "\r\n") if crlf else updated
        items[relative] = old, new
    patch = []
    for relative, (old, new) in sorted(items.items()):
        if old == new:
            continue
        from_file = "a/" + relative if old else "/dev/null"
        lines = list(difflib.unified_diff(old.splitlines(keepends=True),
                   new.splitlines(keepends=True), fromfile=from_file,
                   tofile="b/" + relative, n=3))
        patch.append("diff --git a/%s b/%s\n" % (relative, relative))
        if not old:
            patch.append("new file mode 100644\n")
        patch.extend(lines)
    return "".join(patch)


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def main() -> None:
    """解析两个本地checkout路径，验证HEAD/工作树并生成安全Git补丁。"""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--xpzhu-root", type=Path, required=True)
    ap.add_argument("--hgks-root", type=Path, required=True)
    ap.add_argument("--patch-output", type=Path, default=Path("hgks_integration_patches"))
    ap.add_argument("--apply", action="store_true", help="Make the repository changes")
    ap.add_argument("--allow-different-head", action="store_true")
    args = ap.parse_args()
    roots = {"xpzhu": args.xpzhu_root.resolve(),
             "hgks-v2-1101": args.hgks_root.resolve()}
    for name, root in roots.items():
        if not root.is_dir() or not (root / ".git").exists():
            raise ValueError("not_a_git_checkout:%s" % root)
        actual = git(root, "rev-parse", "HEAD")
        if actual != EXPECTED[name] and not args.allow_different_head:
            raise ValueError("unreviewed_git_head:%s:%s" % (name, actual))
        if args.apply and git(root, "status", "--porcelain"):
            raise ValueError("uncommitted_changes_refuse_to_apply:%s" % name)
    output = args.patch_output.resolve()
    if any(output == root or root in output.parents for root in roots.values()):
        raise ValueError("patch_output_must_be_outside_both_repositories")
    output.mkdir(parents=True, exist_ok=True)
    patches = {}
    for name, root in roots.items():
        patch = make_patch(name, root)
        path = output / (name + ".patch")
        path.write_text(patch, encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "apply", "--check", str(path)],
                       check=True)
        patches[name] = path
    if args.apply:
        applied = []
        try:
            for name, root in roots.items():
                subprocess.run(["git", "-C", str(root), "apply", str(patches[name])], check=True)
                applied.append(name)
        except subprocess.CalledProcessError:
            # A failure on the second checkout must not silently leave the first
            # checkout modified. Only reverse what this command applied.
            for name in reversed(applied):
                subprocess.run(["git", "-C", str(roots[name]), "apply", "-R",
                                str(patches[name])], check=True)
            raise
    print("PATCHES_VALIDATED", {name: str(p) for name, p in patches.items()},
          "APPLIED" if args.apply else "READ_ONLY_PREVIEW")


if __name__ == "__main__":
    main()
