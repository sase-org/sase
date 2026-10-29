"""Report-to-verdict tests for the after-rebase gate runner."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from sase.workflows.commit import rebase_gate_execution as execution
from sase.workflows.commit import rebase_gate_runner as runner
from tests._rebase_gate_runner_helpers import (
    HEAD,
    GateHarness,
    harness as harness,
    make_context,
    make_report,
    write_checker,
)

__all__ = [
    "harness",
    "test_clean_report_permits_push_and_delegates_exact_facts",
    "test_crash_without_report_warns",
    "test_error_report_warns_and_allows_push",
    "test_findings_report_blocks_push",
    "test_malformed_report_warns",
    "test_oversize_report_is_dropped",
    "test_stale_report_warns",
    "test_unsupported_exit_status_warns",
]


def test_clean_report_permits_push_and_delegates_exact_facts(
    harness: GateHarness, tmp_path: Path
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    hook = write_checker(
        tmp_path / "clean.py", exit_code=0, report=make_report("clean")
    )
    harness.configure(root, hook)
    harness.fake_classify("pass")

    seen: dict[str, Any] = {}
    real_popen = subprocess.Popen

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen["args"] = args
        seen["kwargs"] = kwargs
        return real_popen(*args, **kwargs)

    harness.monkeypatch.setattr(subprocess, "Popen", spy)
    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "pass"
    # The hook runs verbatim: changed paths travel in the JSON file, never
    # interpolated into shell text.
    assert seen["args"] == (hook,)
    env = seen["kwargs"]["env"]
    assert env[runner.REBASE_GATE_CONTEXT_ENV].endswith("context.json")
    assert env[runner.REBASE_GATE_RESULT_ENV].endswith("result.json")
    assert seen["kwargs"]["cwd"] == os.path.abspath(str(root))
    assert harness.captured["command"] == {
        "timed_out": False,
        "exit_code": 0,
    }
    assert harness.captured["config"] == {
        "hook_command": hook,
        "timeout_seconds": 5.0,
    }
    assert harness.captured["report"]["status"] == "clean"
    assert harness.captured["report"]["findings"] == []
    assert outcome.metadata_path is not None
    metadata = json.loads(outcome.metadata_path.read_text(encoding="utf-8"))
    assert metadata["verdict"] == "pass"
    assert metadata["changed_path_count"] == 1
    assert metadata["current_head"] == HEAD
    assert metadata["duration_seconds"] >= 0


def test_findings_report_blocks_push(harness: GateHarness, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    report = make_report("findings")
    hook = write_checker(tmp_path / "checker.py", exit_code=1, report=report)
    harness.configure(root, hook)
    harness.fake_classify("block", findings=report["findings"])

    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "block"
    assert harness.captured["command"] == {
        "timed_out": False,
        "exit_code": 1,
    }
    assert harness.captured["report"]["findings"][0]["imported_name"] == "thing"


def test_error_report_warns_and_allows_push(
    harness: GateHarness, tmp_path: Path
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    report = make_report("error")
    report["diagnostics"] = "cannot import third-party dep"
    hook = write_checker(tmp_path / "checker.py", exit_code=1, report=report)
    harness.configure(root, hook)
    harness.fake_classify("warn")

    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "warn"
    assert harness.captured["report"]["status"] == "error"


@pytest.mark.parametrize("hook", ["false", "definitely-missing-sase-gate-bin"])
def test_crash_without_report_warns(
    harness: GateHarness, tmp_path: Path, hook: str
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    harness.configure(root, hook)
    harness.fake_classify("warn")

    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "warn"
    assert harness.captured["report"] is None
    assert harness.captured["command"]["timed_out"] is False
    assert harness.captured["command"]["exit_code"] != 0


def test_stale_report_warns(harness: GateHarness, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    report = make_report("findings", checked_head="0" * 40)
    hook = write_checker(tmp_path / "checker.py", exit_code=1, report=report)
    harness.configure(root, hook)
    harness.fake_classify("warn")

    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "warn"
    assert harness.captured["report"]["checked_head"] == "0" * 40


def test_unsupported_exit_status_warns(harness: GateHarness, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    report = make_report("findings")
    hook = write_checker(tmp_path / "checker.py", exit_code=2, report=report)
    harness.configure(root, hook)
    harness.fake_classify("warn")

    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "warn"
    assert harness.captured["command"]["exit_code"] == 2


def test_malformed_report_warns(harness: GateHarness, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    hook = write_checker(tmp_path / "checker.py", exit_code=0, raw_body="{not json")
    harness.configure(root, hook)
    harness.fake_classify("warn")

    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "warn"
    assert harness.captured["report"] is None


def test_oversize_report_is_dropped(
    harness: GateHarness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(execution, "_RESULT_CAP_BYTES", 64)
    hook = write_checker(
        tmp_path / "checker.py",
        exit_code=0,
        report=make_report("clean"),
    )
    harness.configure(root, hook)
    harness.fake_classify("warn")

    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "warn"
    assert harness.captured["report"] is None
