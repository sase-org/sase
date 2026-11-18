"""Shared builders and fixtures for the artifact-reads loader tests."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui import artifact_reads as artifact_reads_module
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.util.normalized_dirs import normalize_dir
from sase.artifact_read_log import (
    ARTIFACT_READ_LOG_SCHEMA_VERSION,
    ArtifactReadAuditRow,
    ArtifactReadAuditSourceIdentity,
    ArtifactReadEvent,
    read_artifact_read_events,
)

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


def _fake_targeted_query(
    log_path: Path | str,
    *,
    members: list[dict[str, Any]],
    limit: int = 50,
    deduplicate: bool = False,
) -> tuple[list[ArtifactReadAuditRow], ArtifactReadAuditSourceIdentity]:
    """Test adapter for Rust's query; core tests cover the streaming matcher."""
    path = Path(log_path)
    events = read_artifact_read_events(log_path=path)
    normalized_members = [
        (
            normalize_dir(member.get("artifacts_dir")),
            member.get("agent_name"),
        )
        for member in members
    ]
    selected: list[ArtifactReadAuditRow] = []
    seen: set[str] = set()
    for event in events:
        event_dir = normalize_dir(event.artifacts_dir)
        if event_dir is not None:
            member_index = next(
                (
                    index
                    for index, (member_dir, _name) in enumerate(normalized_members)
                    if member_dir is not None and member_dir == event_dir
                ),
                None,
            )
        else:
            member_index = next(
                (
                    index
                    for index, (_directory, name) in enumerate(normalized_members)
                    if name and name == event.agent_name
                ),
                None,
            )
        if member_index is None or (deduplicate and event.id in seen):
            continue
        seen.add(event.id)
        selected.append(ArtifactReadAuditRow(event, member_index))
    selected.sort(key=lambda row: row.event.timestamp, reverse=True)
    if limit > 0:
        selected = selected[:limit]
    try:
        stat = path.stat()
    except FileNotFoundError:
        source = ArtifactReadAuditSourceIdentity(True, 0, 0, 0, 0)
    else:
        source = ArtifactReadAuditSourceIdentity(
            False,
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_dev,
            stat.st_ino,
        )
    return selected, source


@pytest.fixture(autouse=True)
def clear_artifact_reads_cache_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_reads_module._artifact_reads_cache.clear()
    artifact_reads_module._artifact_reads_context_cache.clear()
    monkeypatch.setattr(
        artifact_reads_module, "query_artifact_read_events", _fake_targeted_query
    )


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
