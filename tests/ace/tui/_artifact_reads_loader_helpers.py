"""Shared builders and fixtures for the artifact-reads loader tests."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.tui import artifact_reads as artifact_reads_module
from sase.ace.tui.models.agent import Agent, AgentType
from sase.artifact_read_log import ARTIFACT_READ_LOG_SCHEMA_VERSION, ArtifactReadEvent

_DEFAULT_RESOLVED_PATH = object()


def make_agent(
    *,
    artifacts_dir: Path | None,
    agent_name: str | None = None,
    workspace_dir: Path | None = None,
    raw_suffix: str = "20260524-100000",
    role_suffix: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="artifact-reads-test",
        project_file="/tmp/artifact-reads-test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 24, 10, 0, 0),
        raw_suffix=raw_suffix,
        agent_name=agent_name,
        workspace_dir=str(workspace_dir) if workspace_dir else None,
        artifacts_dir=str(artifacts_dir) if artifacts_dir else None,
        role_suffix=role_suffix,
    )


def make_event(
    *,
    ref: str,
    timestamp: str,
    agent_name: str,
    artifacts_dir: str | None,
    reason: str = "context",
    project: str = "artifact-reads-test",
    read_id: str | None = None,
    resolved_path: str | None | object = _DEFAULT_RESOLVED_PATH,
    recorded_link: bool = False,
) -> ArtifactReadEvent:
    stored_path: str | None
    if resolved_path is _DEFAULT_RESOLVED_PATH:
        stored_path = f"/tmp/artifact-reads-test/{ref}"
    else:
        stored_path = resolved_path if isinstance(resolved_path, str) else None
    return ArtifactReadEvent(
        schema_version=ARTIFACT_READ_LOG_SCHEMA_VERSION,
        id=read_id or ref.replace("/", "_") + timestamp,
        timestamp=timestamp,
        project=project,
        cwd="/tmp/artifact-reads-test",
        ref=ref,
        reason=reason,
        agent_name=agent_name,
        agent_source="SASE_AGENT_NAME",
        artifacts_dir=artifacts_dir,
        recorded_link=recorded_link,
        resolved_path=stored_path,
    )


def write_jsonl(path: Path, events: list[ArtifactReadEvent]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as out:
        for event in events:
            json.dump(asdict(event), out, sort_keys=True)
            out.write("\n")


@pytest.fixture(autouse=True)
def clear_artifact_reads_cache_fixture() -> None:
    artifact_reads_module._artifact_reads_cache.clear()
    artifact_reads_module._artifact_reads_context_cache.clear()
    artifact_reads_module._artifact_reads_snapshot_cache.clear()


@pytest.fixture(name="fake_project")
def fake_project_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setattr(
        artifact_reads_module,
        "project_memory_name",
        lambda _root: "artifact-reads-test",
    )
    sase_home = tmp_path / "sase-home"
    sase_home.mkdir()
    monkeypatch.setenv("HOME", str(sase_home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: sase_home))
    return project_root
