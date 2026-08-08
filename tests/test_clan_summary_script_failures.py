"""Clan summary script failure and output limit coverage."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import BinaryIO, cast

import pytest

from sase.axe.clan_summary_script import (
    CLAN_SUMMARY_MAX_BYTES,
    CLAN_SUMMARY_STDERR_LOG,
)
from tests._clan_summary_persistence_helpers import (
    extract_clan_meta,
    write_script,
)


def test_malformed_summary_script_quoting_never_blocks_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING", logger="sase.axe.clan_summary_script"):
        meta = extract_clan_meta(
            tmp_path,
            'summary_script=[[missing "quote]]',
            monkeypatch,
        )

    assert "clan_summary" not in meta
    assert "No closing quotation" in caplog.text
    artifact = (tmp_path / "artifacts" / CLAN_SUMMARY_STDERR_LOG).read_text(
        encoding="utf-8"
    )
    assert "outcome: not-found" in artifact
    assert "resolution error: No closing quotation" in artifact


@pytest.mark.parametrize(
    ("script_body", "warning", "outcome", "stderr"),
    [
        (
            "import sys\nsys.stderr.write('exit detail\\n')\nraise SystemExit(7)",
            "exited with status 7",
            "exit-code",
            "exit detail",
        ),
        (
            "import sys\nsys.stderr.write('empty detail\\n')\nprint('   ')",
            "produced no output",
            "empty-output",
            "empty detail",
        ),
    ],
    ids=["non-zero", "empty"],
)
def test_failed_summary_script_never_blocks_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    script_body: str,
    warning: str,
    outcome: str,
    stderr: str,
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    write_script(workspace_dir / "make_summary", script_body)
    monkeypatch.setenv("SASE_EPIC_PLAN_REF", "secret-plan-value")

    with caplog.at_level("WARNING", logger="sase.axe.clan_summary_script"):
        meta = extract_clan_meta(
            tmp_path,
            "summary_script=./make_summary",
            monkeypatch,
        )

    assert "clan_summary" not in meta
    assert warning in caplog.text
    assert stderr in caplog.text
    artifact = (tmp_path / "artifacts" / CLAN_SUMMARY_STDERR_LOG).read_text(
        encoding="utf-8"
    )
    assert f"outcome: {outcome}" in artifact
    assert "SASE_EPIC_PLAN_REF" in artifact
    assert "secret-plan-value" not in artifact
    assert stderr in artifact


def test_timed_out_summary_script_never_blocks_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    write_script(
        workspace_dir / "make_summary",
        "import sys\nimport time\nsys.stderr.write('timeout detail\\n')\n"
        "sys.stderr.flush()\ntime.sleep(60)",
    )

    class TimeoutProcess:
        pid = 1

        def __init__(self, *_args: object, **kwargs: object) -> None:
            stderr = cast(BinaryIO, kwargs["stderr"])
            stderr.write(b"timeout detail\n")
            stderr.flush()

        def wait(self, timeout: float | None = None) -> int:
            raise subprocess.TimeoutExpired(cmd=["make_summary"], timeout=timeout)

    monkeypatch.setattr(
        "sase.axe.clan_summary_script.CLAN_SUMMARY_TIMEOUT_SECONDS",
        0.3,
    )
    monkeypatch.setattr("sase.axe.clan_summary_script.subprocess.Popen", TimeoutProcess)
    monkeypatch.setattr("sase.axe.clan_summary_script._kill_process", lambda _p: None)

    with caplog.at_level("WARNING", logger="sase.axe.clan_summary_script"):
        meta = extract_clan_meta(
            tmp_path,
            "summary_script=./make_summary",
            monkeypatch,
        )

    assert "clan_summary" not in meta
    assert "timed out after 0.3s" in caplog.text
    assert "timeout detail" in caplog.text
    artifact = (tmp_path / "artifacts" / CLAN_SUMMARY_STDERR_LOG).read_text(
        encoding="utf-8"
    )
    assert "outcome: timeout" in artifact
    assert "timeout detail" in artifact


def test_missing_summary_script_never_blocks_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING", logger="sase.axe.clan_summary_script"):
        meta = extract_clan_meta(
            tmp_path,
            "summary_script=definitely_missing_summary_script",
            monkeypatch,
        )

    assert "clan_summary" not in meta
    assert "was not found" in caplog.text
    artifact = (tmp_path / "artifacts" / CLAN_SUMMARY_STDERR_LOG).read_text(
        encoding="utf-8"
    )
    assert "outcome: not-found" in artifact
    assert "definitely_missing_summary_script" in artifact


def test_summary_script_output_is_capped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    write_script(
        workspace_dir / "make_summary",
        "print('x' * 40000, end='')",
    )

    with caplog.at_level("WARNING", logger="sase.axe.clan_summary_script"):
        meta = extract_clan_meta(
            tmp_path,
            "summary_script=./make_summary",
            monkeypatch,
        )

    assert meta["clan_summary"] == "x" * CLAN_SUMMARY_MAX_BYTES
    assert "exceeded 32 KiB and was truncated" in caplog.text


def test_literal_summary_is_capped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meta = extract_clan_meta(
        tmp_path,
        f"summary=[[{'x' * 40000}]]",
        monkeypatch,
    )

    assert meta["clan_summary"] == "x" * CLAN_SUMMARY_MAX_BYTES
