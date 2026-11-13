"""Unrelated untracked files must not block a reviewed Git patch install.

The installer must still reject changes to tracked source files. Every patch
is checked by Git before application, and untracked destination collisions
remain errors.
"""

import difflib
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


def _git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def _setup(tmp_path, monkeypatch):
    script = Path(__file__).resolve().parents[1] / "tools" / "install_to_repos.py"
    spec = importlib.util.spec_from_file_location("hgks_1109_installer", script)
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    repos = {}
    patches = {}
    for name in ("xpzhu", "hgks-v2-1101"):
        root = tmp_path / name
        root.mkdir()
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        _git(root, "config", "user.name", "Local Test")
        _git(root, "config", "user.email", "local@example.test")
        source = root / "sample.py"
        old = "first = 1\nsecond = 2\n"
        new = "first = 1\nsecond = 3\n"
        source.write_text(old, encoding="utf-8", newline="\n")
        _git(root, "add", "sample.py")
        _git(root, "commit", "-m", "Initial")
        installer.EXPECTED[name] = _git(root, "rev-parse", "HEAD")
        repos[name] = root
        patches[name] = (
            "diff --git a/sample.py b/sample.py\n"
            + "".join(difflib.unified_diff(
                old.splitlines(keepends=True), new.splitlines(keepends=True),
                fromfile="a/sample.py", tofile="b/sample.py"
            ))
        )
    monkeypatch.setattr(installer, "make_patch", lambda name, _root: patches[name])
    monkeypatch.setattr(sys, "argv", [
        "install_to_repos.py",
        "--xpzhu-root", str(repos["xpzhu"]),
        "--hgks-root", str(repos["hgks-v2-1101"]),
        "--patch-output", str(tmp_path / "patch_review"),
        "--apply",
    ])
    return installer, repos


def test_apply_keeps_unrelated_untracked_files(tmp_path, monkeypatch):
    installer, repos = _setup(tmp_path, monkeypatch)
    hgks = repos["hgks-v2-1101"]
    diagnostic = hgks / ".dsh-probe" / "report.txt"
    diagnostic.parent.mkdir()
    diagnostic.write_text("preserve diagnostic bytes\n", encoding="utf-8")
    grant = hgks / "adb-grant.ps1"
    grant.write_text("# preserve existing helper\n", encoding="utf-8")
    before = (diagnostic.read_bytes(), grant.read_bytes())

    installer.main()

    assert (diagnostic.read_bytes(), grant.read_bytes()) == before
    assert (hgks / "sample.py").read_text(encoding="utf-8").endswith("second = 3\n")
    assert (repos["xpzhu"] / "sample.py").read_text(encoding="utf-8").endswith("second = 3\n")


@pytest.mark.parametrize("stage_modified", [False, True])
def test_apply_refuses_modified_tracked_file(tmp_path, monkeypatch, stage_modified):
    installer, repos = _setup(tmp_path, monkeypatch)
    hgks = repos["hgks-v2-1101"]
    (hgks / "sample.py").write_text("first = 1\nsecond = 999\n", encoding="utf-8")
    if stage_modified:
        _git(hgks, "add", "sample.py")
    with pytest.raises(ValueError, match="uncommitted_tracked_changes_refuse_to_apply:hgks-v2-1101"):
        installer.main()
    assert (repos["xpzhu"] / "sample.py").read_text(encoding="utf-8").endswith("second = 2\n")
