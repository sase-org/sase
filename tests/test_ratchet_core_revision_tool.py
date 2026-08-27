"""Tests for ``tools/ratchet_core_revision``.

The tool proposes moving ``sase-core-revision.txt`` (the git SHA CI builds
sase's Rust core from) forward once sase-core's remote HEAD has moved past
it. It mirrors ``tools/ratchet_core_window``'s ``--check``/``--report-only``/
apply contract and exit codes.
"""

from __future__ import annotations

import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "ratchet_core_revision"

OLD_SHA = "a" * 40
NEW_SHA = "b" * 40


def _load_tool() -> ModuleType:
    loader = SourceFileLoader("ratchet_core_revision_tool", str(SCRIPT))
    spec = importlib.util.spec_from_file_location(
        "ratchet_core_revision_tool",
        SCRIPT,
        loader=loader,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    return _load_tool()


def _write_pin(tmp_path: Path, sha: str = OLD_SHA) -> Path:
    revision_file = tmp_path / "sase-core-revision.txt"
    revision_file.write_text(f"{sha}\n", encoding="utf-8")
    return revision_file


def test_read_pinned_revision_strips_whitespace(
    tool: ModuleType, tmp_path: Path
) -> None:
    revision_file = _write_pin(tmp_path)
    assert tool.read_pinned_revision(revision_file) == OLD_SHA


def test_read_pinned_revision_rejects_non_sha_content(
    tool: ModuleType, tmp_path: Path
) -> None:
    revision_file = tmp_path / "sase-core-revision.txt"
    revision_file.write_text("not-a-sha\n", encoding="utf-8")
    with pytest.raises(tool.RatchetError, match="40 hex character SHA"):
        tool.read_pinned_revision(revision_file)


def test_read_pinned_revision_requires_the_file_to_exist(
    tool: ModuleType, tmp_path: Path
) -> None:
    with pytest.raises(tool.RatchetError, match="missing revision file"):
        tool.read_pinned_revision(tmp_path / "sase-core-revision.txt")


def test_idempotent_when_pin_matches_remote_head(
    tool: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    revision_file = _write_pin(tmp_path, OLD_SHA)

    code = tool.ratchet_core_revision(
        revision_file=revision_file,
        remote_head_fetcher=lambda _url: OLD_SHA,
    )

    assert code == tool.EXIT_OK
    assert revision_file.read_text(encoding="utf-8") == f"{OLD_SHA}\n"
    assert "already matches" in capsys.readouterr().out


def test_check_reports_pending_without_writing(
    tool: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    revision_file = _write_pin(tmp_path, OLD_SHA)

    code = tool.ratchet_core_revision(
        revision_file=revision_file,
        check=True,
        remote_head_fetcher=lambda _url: NEW_SHA,
    )

    assert code == tool.EXIT_RATCHET
    assert revision_file.read_text(encoding="utf-8") == f"{OLD_SHA}\n"
    assert "pending" in capsys.readouterr().out


def test_report_only_prints_diff_without_writing(
    tool: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    revision_file = _write_pin(tmp_path, OLD_SHA)

    code = tool.ratchet_core_revision(
        revision_file=revision_file,
        report_only=True,
        remote_head_fetcher=lambda _url: NEW_SHA,
    )

    assert code == tool.EXIT_RATCHET
    assert revision_file.read_text(encoding="utf-8") == f"{OLD_SHA}\n"
    out = capsys.readouterr().out
    assert f"-{OLD_SHA}" in out
    assert f"+{NEW_SHA}" in out


def test_default_mode_applies_the_new_pin(
    tool: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    revision_file = _write_pin(tmp_path, OLD_SHA)

    code = tool.ratchet_core_revision(
        revision_file=revision_file,
        remote_head_fetcher=lambda _url: NEW_SHA,
    )

    assert code == tool.EXIT_RATCHET
    assert revision_file.read_text(encoding="utf-8") == f"{NEW_SHA}\n"
    assert "applied" in capsys.readouterr().out


def test_fetch_remote_head_rejects_malformed_ls_remote_output(
    tool: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    def _fake_run(
        *_args: object, **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["git"], returncode=0, stdout="not-a-sha\tHEAD\n", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    with pytest.raises(tool.RatchetError, match="did not resolve"):
        tool.fetch_remote_head("https://example.invalid/sase-core.git")


def test_main_check_and_report_only_are_mutually_exclusive(tool: ModuleType) -> None:
    with pytest.raises(SystemExit):
        tool.main(["--check", "--report-only"])


def test_main_wires_check_mode_through(
    tool: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    revision_file = _write_pin(tmp_path, OLD_SHA)
    monkeypatch.setattr(tool, "fetch_remote_head", lambda _url: NEW_SHA)

    code = tool.main(["--revision-file", str(revision_file), "--check"])

    assert code == tool.EXIT_RATCHET
    assert revision_file.read_text(encoding="utf-8") == f"{OLD_SHA}\n"


def test_main_surfaces_ratchet_errors_as_could_not_determine(
    tool: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = tool.main(
        ["--revision-file", str(tmp_path / "missing-revision.txt"), "--check"]
    )

    assert code == tool.EXIT_COULD_NOT_DETERMINE
    assert "missing revision file" in capsys.readouterr().err
