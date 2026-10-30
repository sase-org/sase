"""Registration and chop tests for the ``artifact_retention`` housekeeping job."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tomllib

import pytest
import yaml

import sase.scripts.sase_chop_artifact_retention as retention_chop
from sase.core.artifact_file_explicit import read_artifact_file_index
from sase.core.artifact_file_protection import ProtectedArtifactIds
from sase.core.artifact_file_retention_pass import (
    _ArtifactRetentionPassResult,
    _read_artifact_retention_stamp,
)
from tests.test_axe_run_agent_exec_finalize_retention import (
    _patch_protections,
    _patch_retention_config,
    _seed_store,
)


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
    assert project["project"]["scripts"]["sase_job_artifact_retention"] == (
        "sase.scripts.sase_chop_artifact_retention:main"
    )
    defaults = yaml.safe_load(
        Path("src/sase/default_config.yml").read_text(encoding="utf-8")
    )
    jobs = defaults["axe"]["routines"]["housekeeping"]["jobs"]
    assert any(
        job["name"] == "artifact_retention"
        and job["script"] == "sase_job_artifact_retention"
        for job in jobs
    )


def test_job_runs_and_stamps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index, old, new, explicit, _expired = _seed_store(tmp_path, monkeypatch)
    _patch_retention_config(monkeypatch, enabled=True)
    _patch_protections(
        monkeypatch,
        ProtectedArtifactIds(
            referenced_ids=frozenset(),
            consumed_ids=frozenset(),
            sources_scanned=(),
            sources_unavailable=(),
        ),
    )
    runtime = _Runtime()

    result = retention_chop._run(runtime)

    assert runtime.summary["outcome"] == "enforced"
    assert runtime.summary["stamped"] == 1
    assert runtime.reason is None
    assert result.status == "ok"
    stamp = _read_artifact_retention_stamp()
    assert stamp is not None
    assert stamp["outcome"] == "enforced"
    assert stamp["rows_trashed"] == 1
    remaining = {row.id for row in read_artifact_file_index(index)}
    assert old.id not in remaining
    assert {new.id, explicit.id} <= remaining


def test_job_stamps_disabled_config_without_trashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index, *_rest = _seed_store(tmp_path, monkeypatch)
    _patch_retention_config(monkeypatch, enabled=False)
    before = index.read_bytes()
    runtime = _Runtime()

    result = retention_chop._run(runtime)

    assert runtime.summary["outcome"] == "disabled"
    assert runtime.reason == "disabled"
    assert result.status == "no_op"
    assert index.read_bytes() == before
    stamp = _read_artifact_retention_stamp()
    assert stamp is not None
    assert stamp["outcome"] == "disabled"


def test_job_reports_lock_busy_without_stamping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    monkeypatch.setattr(
        retention_chop,
        "enforce_artifact_retention",
        lambda: _ArtifactRetentionPassResult(outcome="lock_busy", stamped=False),
    )
    runtime = _Runtime()

    result = retention_chop._run(runtime)

    assert runtime.summary["outcome"] == "lock_busy"
    assert runtime.reason == "lock_busy"
    assert runtime.summary["stamped"] == 0
    assert result.status == "no_op"


def test_job_marks_failed_pass_check_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    monkeypatch.setattr(
        retention_chop,
        "enforce_artifact_retention",
        lambda: _ArtifactRetentionPassResult(
            outcome="failed",
            stamped=True,
            error="boom",
        ),
    )
    runtime = _Runtime()

    result = retention_chop._run(runtime)

    assert runtime.reason == "failed"
    assert result.status == "check_error"
    assert any("boom" in message for message in runtime.log.messages)
