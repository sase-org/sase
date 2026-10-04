"""Tests for the editable update core revision-pin gate helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

from sase.dev_update.core_pin import core_contains_revision, read_core_pin


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return result.stdout.strip()


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "--quiet", "--initial-branch=main", str(root)],
        check=True,
        timeout=10,
    )
    _git(root, "config", "user.name", "SASE test")
    _git(root, "config", "user.email", "sase-test@example.invalid")


def _commit_file(root: Path, path: str, content: str, subject: str) -> str:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(root, "add", path)
    _git(root, "commit", "--quiet", "-m", subject)
    return _git(root, "rev-parse", "HEAD")


def _host_repo(tmp_path: Path, pin_text: str | None) -> Path:
    host = tmp_path / "sase"
    _init_repo(host)
    _commit_file(
        host,
        "sase/sase.yml",
        "repos:\n  linked:\n    - name: sase-core\n      revision_pin: "
        "sase-core-revision.txt\n",
        "add core revision config",
    )
    if pin_text is not None:
        _commit_file(host, "sase-core-revision.txt", pin_text, "set core revision")
    return host


def test_read_core_pin_reads_configured_file_at_ref(tmp_path: Path) -> None:
    core_root = tmp_path / "sase-core"
    _init_repo(core_root)
    _commit_file(core_root, "src/lib.rs", "// first\n", "first")
    second = _commit_file(core_root, "src/lib.rs", "// second\n", "second")
    host_root = _host_repo(tmp_path, f"{second}\n")

    pin = read_core_pin(host_root, "HEAD")

    assert pin is not None
    assert pin.pin_file == "sase-core-revision.txt"
    assert pin.sha == second
    assert pin.short_sha == second[:12]


def test_core_contains_revision_checks_object_and_ancestry(tmp_path: Path) -> None:
    core_root = tmp_path / "sase-core"
    _init_repo(core_root)
    first = _commit_file(core_root, "src/lib.rs", "// first\n", "first")
    second = _commit_file(core_root, "src/lib.rs", "// second\n", "second")

    assert core_contains_revision(core_root, second, first) is False
    assert core_contains_revision(core_root, second, second) is True
    assert core_contains_revision(core_root, "0" * 40, "HEAD") is False


def test_read_core_pin_returns_none_for_missing_or_invalid_pin(tmp_path: Path) -> None:
    missing_file_host = _host_repo(tmp_path / "missing", None)
    assert read_core_pin(missing_file_host, "HEAD") is None

    malformed_host = _host_repo(tmp_path / "malformed", "not-a-sha\n")
    assert read_core_pin(malformed_host, "HEAD") is None


def test_read_core_pin_returns_none_without_pin_configuration(tmp_path: Path) -> None:
    host_root = tmp_path / "unconfigured"
    _init_repo(host_root)
    _commit_file(host_root, "README.md", "no pin config\n", "initial")

    assert read_core_pin(host_root, "HEAD") is None
