"""Tests for phase-aware commit-hook execution and diagnostics."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

import pytest

import sase.workflows.commit.command_hooks as command_hooks
from sase.workflows.commit.command_hooks import (
    _HookRunResult,
    run_after_commit_hook,
    run_before_commit_hook,
)


@pytest.mark.parametrize("phase", ["before", "after"])
def test_run_commit_hook_uses_nested_phase_config(phase: str, tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    run = MagicMock(
        return_value=_HookRunResult(
            returncode=0,
            duration_seconds=0.1,
            metadata_path=tmp_path / "hook.json",
            stdout_tail="",
            stderr_tail="",
            stdout_truncated=False,
            stderr_truncated=False,
        )
    )
    with (
        patch(
            "sase.workflows.commit.command_hooks.load_merged_config",
            return_value={"commit_hooks": {phase: "hook command"}},
        ),
        patch(
            "sase.workflows.commit.command_hooks.get_repo_root",
            return_value=str(tmp_path),
        ) as get_repo_root,
        patch("sase.workflows.commit.command_hooks._run_hook_command", run),
    ):
        hook = run_before_commit_hook if phase == "before" else run_after_commit_hook
        assert hook(str(nested)) is True

    get_repo_root.assert_called_once_with(str(nested))
    run.assert_called_once_with("hook command", phase=phase, repo_root=str(tmp_path))


@pytest.mark.parametrize(
    "config",
    [{}, {"commit_hooks": {}}, {"commit_hooks": {"before": ""}}],
)
def test_run_commit_hook_skips_empty_commands(config: dict, tmp_path: Path) -> None:
    with (
        patch(
            "sase.workflows.commit.command_hooks.load_merged_config",
            return_value=config,
        ),
        patch("sase.workflows.commit.command_hooks._run_hook_command") as run,
    ):
        assert run_before_commit_hook(str(tmp_path)) is True

    run.assert_not_called()


def test_run_commit_hook_prints_phase_specific_output_tail_and_log_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    command = (
        'for i in $(seq 0 59); do echo "out $i"; done; echo "err final" >&2; exit 1'
    )
    with (
        patch(
            "sase.workflows.commit.command_hooks.load_merged_config",
            return_value={"commit_hooks": {"after": command}},
        ),
        patch(
            "sase.workflows.commit.command_hooks.get_repo_root",
            return_value=str(tmp_path),
        ),
    ):
        assert run_after_commit_hook(str(tmp_path)) is False

    captured = capsys.readouterr()
    assert "After commit hook failed (exit 1):" in captured.out
    assert "After commit hook evidence:" in captured.out
    assert "after commit hook output tail" in captured.err
    assert "out 0" not in captured.err
    assert "out 59" in captured.err
    assert "err final" in captured.err
    metadata_files = list((tmp_path / "artifacts" / "commit_hooks").glob("*.json"))
    assert len(metadata_files) == 1
    metadata = json.loads(metadata_files[0].read_text(encoding="utf-8"))
    assert metadata["phase"] == "after"
    assert metadata["status"] == "failed"
    assert metadata["returncode"] == 1


def test_hook_command_writes_bounded_logs_and_recent_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setattr(command_hooks, "_LOG_CAP_BYTES", 24)
    script = tmp_path / "hook.py"
    script.write_text(
        "import sys\n"
        "sys.stdout.write('x' * 80 + '\\n')\n"
        "sys.stderr.write('tail-marker\\n')\n",
        encoding="utf-8",
    )

    result = command_hooks._run_hook_command(
        f"{sys.executable} {script}",
        phase="before",
        repo_root=str(tmp_path),
    )

    assert result.returncode == 0
    assert result.stdout_truncated is True
    assert "tail-marker" in result.stderr_tail
    metadata = command_hooks.load_latest_commit_hook_metadata(
        tmp_path / "artifacts", str(tmp_path)
    )
    assert metadata is not None
    paths = metadata["paths"]
    assert isinstance(paths, dict)
    stdout_log = Path(str(paths["stdout"])).read_text(encoding="utf-8")
    stdout_tail = Path(str(paths["stdout_tail"])).read_text(encoding="utf-8")
    assert "truncated after 24 bytes" in stdout_log
    assert len(stdout_tail) <= command_hooks._TAIL_CAP_BYTES
    assert "x" in stdout_tail
