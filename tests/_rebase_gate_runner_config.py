"""Configuration and validation tests for the after-rebase gate runner."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from sase.workflows.commit import rebase_gate_runner as runner
from sase.workflows.commit import rebase_gate_settings as settings
from tests._rebase_gate_runner_helpers import (
    GateHarness,
    harness as harness,
    make_context,
    make_report,
    write_checker,
)

__all__ = [
    "harness",
    "test_config_load_failure_warns",
    "test_configuration_is_isolated_between_project_roots",
    "test_disabled_hook_launches_no_process",
    "test_facade_failure_warns_and_keeps_evidence",
    "test_invalid_timeout_is_preflighted_before_context_git_queries",
    "test_invalid_timeout_warns_without_launching",
    "test_non_string_hook_warns_without_launching",
]


def test_configuration_is_isolated_between_project_roots(
    harness: GateHarness, tmp_path: Path
) -> None:
    root_a = tmp_path / "proj-a"
    root_b = tmp_path / "proj-b"
    root_a.mkdir()
    root_b.mkdir()
    harness.configure(root_a, "true", timeout=2.0)
    harness.configure(root_b, "true", timeout=4.0)
    harness.fake_classify("pass")

    outcome_a = runner.run_after_rebase_gate(make_context(), str(root_a))
    outcome_b = runner.run_after_rebase_gate(make_context(), str(root_b))

    assert outcome_a.decision["verdict"] == "pass"
    assert outcome_b.decision["verdict"] == "pass"
    assert harness.loaded_for[-2:] == [
        os.path.abspath(str(root_a)),
        os.path.abspath(str(root_b)),
    ]
    # The second run's captured config proves per-root resolution: the
    # harness returns each root's own layer.
    assert harness.captured["config"]["timeout_seconds"] == 4.0


def test_disabled_hook_launches_no_process(
    harness: GateHarness, tmp_path: Path
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    harness.configure(root, "   ")
    harness.fake_classify("skip")

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("disabled gate must not launch a process")

    harness.monkeypatch.setattr(subprocess, "Popen", boom)
    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "skip"
    assert outcome.metadata_path is None
    assert harness.captured["config"] == {
        "hook_command": "",
        "timeout_seconds": 5.0,
    }
    assert harness.captured["command"] == {}
    assert harness.captured["report"] is None


@pytest.mark.parametrize(
    "timeout",
    ["ten", True, [5], {"s": 5}, 0, -1, 30.1, float("inf"), float("nan")],
)
def test_invalid_timeout_warns_without_launching(
    harness: GateHarness, tmp_path: Path, timeout: Any
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    harness.configure(root, "true", timeout=timeout)
    harness.fake_classify("pass")

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("invalid config must not launch a process")

    harness.monkeypatch.setattr(subprocess, "Popen", boom)
    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "warn"
    assert outcome.metadata_path is None


def test_invalid_timeout_is_preflighted_before_context_git_queries(
    harness: GateHarness, tmp_path: Path
) -> None:
    from sase.workflows.commit.rebase_gate_coordinator import (
        begin_rebase_gate_capture,
    )

    root = tmp_path / "repo"
    root.mkdir()
    harness.configure(root, "true", timeout=float("nan"))
    git_calls: list[tuple[list[str], str]] = []

    def run(args: list[str], cwd: str, **kwargs: Any) -> Any:
        git_calls.append((args, cwd))
        raise AssertionError("invalid config must stop before context discovery")

    capture = begin_rebase_gate_capture(str(root), run, "origin/master", payload={})

    assert capture is None
    assert git_calls == []


def test_non_string_hook_warns_without_launching(
    harness: GateHarness, tmp_path: Path
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    harness.configure(root, ["true"], timeout=5.0)
    harness.fake_classify("pass")

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("invalid config must not launch a process")

    harness.monkeypatch.setattr(subprocess, "Popen", boom)
    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "warn"
    assert "after_rebase" in outcome.decision["reason"]


def test_facade_failure_warns_and_keeps_evidence(
    harness: GateHarness, tmp_path: Path
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    hook = write_checker(
        tmp_path / "clean.py", exit_code=0, report=make_report("clean")
    )
    harness.configure(root, hook)

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("binding exploded")

    harness.monkeypatch.setattr(
        "sase.core.rebase_gate.classify_rebase_gate_result", broken
    )
    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "warn"
    assert "binding exploded" in (outcome.decision["diagnostics"] or "")
    assert outcome.metadata_path is not None
    metadata = json.loads(outcome.metadata_path.read_text(encoding="utf-8"))
    assert metadata["status"] == "warned"


def test_config_load_failure_warns(harness: GateHarness, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    def broken(path: Path) -> dict[str, Any]:
        raise RuntimeError("config store exploded")

    harness.monkeypatch.setattr(settings, "load_merged_config_for_local_path", broken)
    harness.fake_classify("pass")
    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "warn"
    assert outcome.metadata_path is None
