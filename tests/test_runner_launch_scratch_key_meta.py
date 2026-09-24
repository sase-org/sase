"""The runner records its launch scratch key so user kills can find its tree."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.axe import run_agent_markers, run_agent_runner_bootstrap
from sase.env_contracts import SASE_LAUNCH_SCRATCH_KEY_ENV


def _bootstrap_meta(tmp_path: Path) -> dict[str, Any]:
    with patch.object(run_agent_runner_bootstrap, "write_agent_meta") as write:
        run_agent_runner_bootstrap._write_bootstrap_agent_meta(
            str(tmp_path), output_path="out.log", refreshed=False
        )
    return write.call_args.args[1]


def test_bootstrap_meta_records_the_launch_scratch_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(SASE_LAUNCH_SCRATCH_KEY_ENV, "agent-ws3-20260924")

    meta = _bootstrap_meta(tmp_path)

    assert meta["launch_scratch_key"] == "agent-ws3-20260924"
    assert meta["pid"] == os.getpid()


def test_bootstrap_meta_omits_the_key_when_the_launch_set_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(SASE_LAUNCH_SCRATCH_KEY_ENV, raising=False)

    assert "launch_scratch_key" not in _bootstrap_meta(tmp_path)


def _marker_meta(pid: int, tmp_path: Path) -> dict[str, Any]:
    meta: dict[str, Any] = {"pid": pid}
    with patch.object(run_agent_markers, "write_agent_meta_atomic"):
        run_agent_markers.write_agent_meta(str(tmp_path), meta)
    return meta


def test_marker_write_records_the_key_only_for_the_writing_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(SASE_LAUNCH_SCRATCH_KEY_ENV, "runner-key")

    assert _marker_meta(os.getpid(), tmp_path)["launch_scratch_key"] == "runner-key"
    # A TUI or CLI rewriting another agent's meta must never stamp its own key.
    assert "launch_scratch_key" not in _marker_meta(os.getpid() + 1, tmp_path)


def test_marker_write_keeps_an_already_recorded_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(SASE_LAUNCH_SCRATCH_KEY_ENV, "new-key")
    meta: dict[str, Any] = {"pid": os.getpid(), "launch_scratch_key": "old-key"}

    with patch.object(run_agent_markers, "write_agent_meta_atomic"):
        run_agent_markers.write_agent_meta(str(tmp_path), meta)

    assert meta["launch_scratch_key"] == "old-key"
