"""Shared builders and fixtures for the glossary-reads loader tests."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.tui import glossary_reads as glossary_reads_module
from sase.ace.tui.models.agent import Agent, AgentType
from sase.glossary.read_log import (
    GLOSSARY_READ_LOG_SCHEMA_VERSION,
    GlossaryReadEvent,
)


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
        cl_name="glossary-reads-test",
        project_file="/tmp/glossary-reads-test.sase",
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
    terms: tuple[str, ...],
    timestamp: str,
    agent_name: str,
    artifacts_dir: str | None,
    related_terms: tuple[str, ...] = (),
    reason: str = "context",
    project: str = "glossary-reads-test",
    read_id: str | None = None,
    source_path: str | None = "/tmp/glossary-reads-test/sase/sase.yml",
) -> GlossaryReadEvent:
    return GlossaryReadEvent(
        schema_version=GLOSSARY_READ_LOG_SCHEMA_VERSION,
        id=read_id or "_".join(terms).replace(" ", "_") + timestamp,
        timestamp=timestamp,
        project=project,
        cwd="/tmp/glossary-reads-test",
        agent_name=agent_name,
        agent_source="SASE_AGENT_NAME",
        artifacts_dir=artifacts_dir,
        reason=reason,
        terms=terms,
        related_terms=related_terms,
        depth_limit=None,
        definition_bytes=128,
        source_path=source_path,
    )


def write_jsonl(path: Path, events: list[GlossaryReadEvent]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as out:
        for event in events:
            json.dump(asdict(event), out, sort_keys=True)
            out.write("\n")


@pytest.fixture(autouse=True)
def clear_glossary_reads_cache_fixture() -> None:
    glossary_reads_module._glossary_reads_cache.clear()
    glossary_reads_module._glossary_reads_context_cache.clear()
    glossary_reads_module._glossary_reads_snapshot_cache.clear()


@pytest.fixture(name="fake_project")
def fake_project_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setattr(
        glossary_reads_module,
        "project_memory_name",
        lambda _root: "glossary-reads-test",
    )
    sase_home = tmp_path / "sase-home"
    sase_home.mkdir()
    monkeypatch.setenv("HOME", str(sase_home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: sase_home))
    return project_root
