"""Regression: Windows must not rewrite line endings inside generated Git patches."""

import difflib
import importlib.util
import subprocess
import sys
from pathlib import Path


def _git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def test_apply_preserves_lf_and_crlf(tmp_path, monkeypatch):
    installer_path = Path(__file__).resolve().parents[1] / "tools" / "install_to_repos.py"
    spec = importlib.util.spec_from_file_location("install_to_repos", installer_path)
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)

    patches = {}
    roots = {}
    for name, line_ending in (("xpzhu", "\n"), ("hgks-v2-1101", "\r\n")):
        root = tmp_path / name
        root.mkdir()
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        _git(root, "config", "user.name", "Test")
        _git(root, "config", "user.email", "test@example.org")
        source = root / "sample.py"
        old = f"first = 1{line_ending}second = 2{line_ending}"
        new = f"first = 1{line_ending}second = 3{line_ending}"
        source.write_bytes(old.encode("utf-8"))
        _git(root, "add", "sample.py")
        _git(root, "commit", "-m", "Initial sample")
        installer.EXPECTED[name] = _git(root, "rev-parse", "HEAD")
        roots[name] = root
        patches[name] = (
            "diff --git a/sample.py b/sample.py\n"
            + "".join(difflib.unified_diff(
                old.splitlines(keepends=True), new.splitlines(keepends=True),
                fromfile="a/sample.py", tofile="b/sample.py"))
        )

    monkeypatch.setattr(installer, "make_patch", lambda name, _root: patches[name])
    output = tmp_path / "patches"
    monkeypatch.setattr(sys, "argv", [
        "install_to_repos.py", "--xpzhu-root", str(roots["xpzhu"]),
        "--hgks-root", str(roots["hgks-v2-1101"]),
        "--patch-output", str(output), "--apply",
    ])
    installer.main()

    for name, root in roots.items():
        data = (root / "sample.py").read_bytes()
        assert b"second = 3" in data
        if name == "hgks-v2-1101":
            assert b"\r\n" in data
            assert b"\r\r\n" not in data
        else:
            assert b"\r" not in data
