"""Tests for commit precommit hook diagnostics."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from sase.workflows.commit.precommit_hooks import run_precommit


def test_run_precommit_prints_captured_output_tail(tmp_path: Path, capsys) -> None:
    result = subprocess.CompletedProcess(
        args="just fix",
        returncode=1,
        stdout="\n".join(f"out {i}" for i in range(60)),
        stderr="err final\n",
    )
    with (
        patch(
            "sase.workflows.commit.precommit_hooks.load_merged_config",
            return_value={"precommit_command": "just fix"},
        ),
        patch(
            "sase.workflows.commit.precommit_hooks.subprocess.run", return_value=result
        ),
    ):
        assert run_precommit(str(tmp_path)) is False

    captured = capsys.readouterr()
    assert "precommit output tail" in captured.err
    assert "out 0" not in captured.err
    assert "out 59" in captured.err
    assert "err final" in captured.err
