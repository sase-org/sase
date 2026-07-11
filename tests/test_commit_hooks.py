"""Tests for phase-aware commit-hook execution and diagnostics."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.workflows.commit.commit_hooks import (
    run_after_commit_hook,
    run_before_commit_hook,
)


@pytest.mark.parametrize("phase", ["before", "after"])
def test_run_commit_hook_uses_nested_phase_config(phase: str, tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    run = MagicMock(
        return_value=subprocess.CompletedProcess(
            args="hook command", returncode=0, stdout="", stderr=""
        )
    )
    with (
        patch(
            "sase.workflows.commit.commit_hooks.load_merged_config",
            return_value={"commit_hooks": {phase: "hook command"}},
        ),
        patch(
            "sase.workflows.commit.commit_hooks._get_repo_root",
            return_value=str(tmp_path),
        ) as get_repo_root,
        patch("sase.workflows.commit.commit_hooks.subprocess.run", run),
    ):
        hook = run_before_commit_hook if phase == "before" else run_after_commit_hook
        assert hook(str(nested)) is True

    get_repo_root.assert_called_once_with(str(nested))
    run.assert_called_once_with(
        "hook command",
        shell=True,
        cwd=str(tmp_path),
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "config",
    [{}, {"commit_hooks": {}}, {"commit_hooks": {"before": ""}}],
)
def test_run_commit_hook_skips_empty_commands(config: dict, tmp_path: Path) -> None:
    with (
        patch(
            "sase.workflows.commit.commit_hooks.load_merged_config",
            return_value=config,
        ),
        patch("sase.workflows.commit.commit_hooks.subprocess.run") as run,
    ):
        assert run_before_commit_hook(str(tmp_path)) is True

    run.assert_not_called()


def test_run_commit_hook_prints_phase_specific_output_tail(
    tmp_path: Path, capsys
) -> None:
    result = subprocess.CompletedProcess(
        args="just fix",
        returncode=1,
        stdout="\n".join(f"out {i}" for i in range(60)),
        stderr="err final\n",
    )
    with (
        patch(
            "sase.workflows.commit.commit_hooks.load_merged_config",
            return_value={"commit_hooks": {"after": "just fix"}},
        ),
        patch(
            "sase.workflows.commit.commit_hooks._get_repo_root",
            return_value=str(tmp_path),
        ),
        patch("sase.workflows.commit.commit_hooks.subprocess.run", return_value=result),
    ):
        assert run_after_commit_hook(str(tmp_path)) is False

    captured = capsys.readouterr()
    assert "After commit hook failed (exit 1): just fix" in captured.out
    assert "after commit hook output tail" in captured.err
    assert "out 0" not in captured.err
    assert "out 59" in captured.err
    assert "err final" in captured.err
