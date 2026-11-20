"""Registration and chop tests for the ``state_retention`` housekeeping job."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tomllib

import yaml

import sase.scripts.sase_chop_state_retention as retention_chop
from sase.core.disk_footprint_models import DiskReapStep
from sase.core.disk_footprint_reap_tool_run import EmptyLogDirSweep
from sase.core.state_retention import StateRetentionOutcome


class _Logger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def __call__(self, message: str, _color: str | None = None) -> None:
        self.messages.append(message)

    def warning(self, message: str) -> None:
        self.messages.append(message)


class _Runtime:
    def __init__(self) -> None:
        self.summary = None
        self.reason = None
        self.log = _Logger()

    def emit_summary(self, summary, *, reason=None):
        self.summary = summary
        self.reason = reason
        return SimpleNamespace(status="no_op" if reason else "ok", reason=reason)


def test_hourly_job_is_registered() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["scripts"]["sase_job_state_retention"] == (
        "sase.scripts.sase_chop_state_retention:main"
    )
    defaults = yaml.safe_load(
        Path("src/sase/default_config.yml").read_text(encoding="utf-8")
    )
    jobs = defaults["axe"]["routines"]["housekeeping"]["jobs"]
    assert any(
        job["name"] == "state_retention" and job["script"] == "sase_job_state_retention"
        for job in jobs
    )


def test_chop_applies_owner_and_reports_empty_dirs(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.scripts.sase_chop_state_retention.run_state_retention",
        lambda: StateRetentionOutcome(
            owner_applied=True,
            owner_skipped=False,
            owner_step=DiskReapStep(
                owner="tool_run_retention",
                mode="apply",
                summary="removed 1 file(s)",
                changed=True,
                details={
                    "summary_rows": 1,
                    "removed_files": 1,
                    "protected_unsettled": 0,
                },
            ),
            empty_dirs=EmptyLogDirSweep(2, 1, 1, (), ("/tmp/run-empty",)),
            interval_seconds=3600,
            errors=(),
        ),
    )
    runtime = _Runtime()
    result = retention_chop._run(runtime)
    assert result.status == "ok"
    assert runtime.reason is None
    assert runtime.summary["owner_applied"] == 1
    assert runtime.summary["empty_dirs_removed"] == 1


def test_chop_interval_gated_when_owner_skipped(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.scripts.sase_chop_state_retention.run_state_retention",
        lambda: StateRetentionOutcome(
            owner_applied=False,
            owner_skipped=True,
            owner_step=None,
            empty_dirs=EmptyLogDirSweep(0, 0, 0, (), ()),
            interval_seconds=3600,
            errors=(),
        ),
    )
    runtime = _Runtime()
    result = retention_chop._run(runtime)
    assert result.status == "no_op"
    assert runtime.reason == "interval_gated"
