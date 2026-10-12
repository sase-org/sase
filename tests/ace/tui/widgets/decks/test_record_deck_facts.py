"""Lifecycle and Provenance cards for ≡ RECORD (epic sase-1jm.4.2, ``facts``).

Covers card content for an inbox agent, a hydrated archived agent, an
inbox clan container, and a thin agent with no artifacts dir. Also
proves the extras loader owns the I/O: card builders do none on the
pump.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.console import Group
from rich.text import Text

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.decks.record.facts import (
    FactsExtras,
    lifecycle_card,
    load_facts_extras,
    provenance_card,
)
from sase.ace.tui.widgets.decks.record.model import (
    RecordArchiveFacts,
    record_subject_from_agent,
)
from sase.ace.tui.widgets.renderable_text import renderable_to_text
from sase.core.time import format_local


def _agent(**overrides: object) -> Agent:
    kwargs: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "demo-code",
        "project_file": "/tmp/p.sase",
        "status": "RUNNING",
        "start_time": datetime(2026, 9, 27, 7, 30, 0),
        "raw_suffix": "20260927073000-code",
    }
    kwargs.update(overrides)
    return Agent(**kwargs)  # type: ignore[arg-type]


def _card_text(card: object) -> str:
    renderables = getattr(card, "renderables", ())
    return renderable_to_text(Group(*renderables)) or ""


def test_inbox_lifecycle_and_provenance_cards() -> None:
    agent = _agent(
        agent_name="athena",
        status="DONE",
        stop_time=datetime(2026, 9, 27, 8, 0, 0),
        project_display_name="Demo",
        workspace_num=3,
        workspace_dir="/tmp/ws",
        model="opus",
        llm_provider="claude",
        reasoning_effort="xhigh",
        agent_tab="review",
        tribe="core",
        source_username="bryan",
        source_machine="athena",
        source_run_id="run-1",
    )
    subject = record_subject_from_agent(agent)
    extras = FactsExtras(reference="agent:athena", chat_path="/tmp/chat.json")
    life = _card_text(lifecycle_card(subject, extras))
    prov = _card_text(provenance_card(subject, extras))
    assert life.splitlines()[0] == "@agent:athena"
    assert "@agent:athena" in life
    assert "Inbox" in life
    assert "DONE" in life
    assert "Outcome:" not in life
    assert format_local(agent.start_time) in life
    assert format_local(agent.stop_time) in life
    assert "end not recorded" not in life
    assert "Viewable: yes" in life
    assert "Restorable: yes" in life
    assert "Restartable: yes" in life
    assert "Project: Demo" in prov
    assert "Workspace: #3" in prov
    assert "/tmp/ws" in prov
    assert "opus" in prov
    assert "Agent tab: review" in prov
    assert "Tribe: core" in prov
    assert "bryan@athena" in prov
    assert "Source run: run-1" in prov
    assert "/tmp/chat.json" in prov


def test_hydrated_archived_lifecycle_uses_light_row_and_index() -> None:
    agent = _agent(
        agent_name="archived-run",
        status="FAILED",
        stop_time=None,
        _archive_read_only=True,
        historically_viewable=True,
        durably_revivable=False,
        restartable=False,
        missing_requirements=("chat",),
    )
    archive = RecordArchiveFacts(
        outcome="failed",
        time_basis="ended",
        last_activity="2026-10-08T16:06:00Z",
        start_time="2026-10-08T15:06:00Z",
        restorable=False,
    )
    subject = record_subject_from_agent(
        agent, archive=archive, bundle_path="/tmp/dismissed/run.json"
    )
    extras = FactsExtras(
        reference="agent:archived-run",
        dismissed_at="2026-10-08T18:20:00Z",
        times_revived=2,
        bundle_path="/tmp/dismissed/run.json",
    )
    life = _card_text(lifecycle_card(subject, extras))
    prov = _card_text(provenance_card(subject, extras))
    assert life.splitlines()[0] == "@agent:archived-run"
    assert "Archive" in life
    assert "FAILED" in life
    assert "✗ failed" in life
    assert "end not recorded" in life
    assert "Time basis: ended" in life
    assert "Revived: ×2" in life
    assert "Restorable: no" in life
    assert "Restartable: no" in life
    assert "Missing: chat" in life
    assert "Last activity:" in life
    assert "Dismissed:" in life
    assert "/tmp/dismissed/run.json" in prov


def test_archived_started_basis_is_dim_italic() -> None:
    agent = _agent(agent_name="partial", status="RUNNING", _archive_read_only=True)
    archive = RecordArchiveFacts(outcome="interrupted", time_basis="started")
    subject = record_subject_from_agent(agent, archive=archive)
    life = lifecycle_card(subject, FactsExtras())
    body = life.renderables[0]
    assert isinstance(body, Text)
    spans = {body.plain[span.start : span.end]: span.style for span in body.spans}
    assert any(
        "started" in fragment and "italic" in str(style)
        for fragment, style in spans.items()
    )
    text = _card_text(life)
    assert "○ WAS RUNNING" in text
    assert "Time basis: started" in text


def test_inbox_clan_container_cards() -> None:
    agent = _agent(
        agent_name="research.45",
        status="RUNNING",
        is_clan_container=True,
        clan_tribe="research",
        project_display_name="Demo",
    )
    subject = record_subject_from_agent(agent)
    assert subject.kind == "container"
    life = _card_text(lifecycle_card(subject, FactsExtras()))
    prov = _card_text(provenance_card(subject, FactsExtras()))
    assert "research.45" in life
    assert "Inbox" in life
    assert "RUNNING" in life
    assert "Outcome:" not in life
    assert "Clan tribe: research" in prov
    assert "Project: Demo" in prov
    assert "Agent tab: main" in prov


def test_thin_agent_artifacts_dir_not_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(agent_name="thin", artifacts_dir=None, model=None)
    subject = record_subject_from_agent(agent)
    monkeypatch.setattr(
        "sase.artifact_ref_entries.reference_for_agent_name",
        lambda name: f"@agent:{name}",
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_bundle_index.query_summaries",
        lambda *_a, **_k: None,
    )
    extras = load_facts_extras(subject)
    assert extras.artifacts_dir is None
    assert extras.chat_path is None
    prov = _card_text(provenance_card(subject, extras))
    assert "not recorded" in prov
    life = _card_text(lifecycle_card(subject, extras))
    assert life.splitlines()[0] == "@agent:thin"
    assert "@agent:thin" in life
    assert "Inbox" in life


def test_card_builders_do_no_io_on_the_pump(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _ref(name: str) -> str:
        calls.append("reference")
        return f"@agent:{name}"

    def _query(*_args: object, **_kwargs: object) -> list[object]:
        calls.append("index")
        return []

    def _resolve(path: object) -> Path:
        calls.append("artifacts")
        return Path(str(path))

    monkeypatch.setattr(
        "sase.artifact_ref_entries.reference_for_agent_name",
        _ref,
    )
    monkeypatch.setattr(
        "sase.core.agent_artifact_paths.resolve_agent_artifact_path",
        _resolve,
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_bundle_index.query_summaries",
        _query,
    )
    subject = record_subject_from_agent(
        _agent(agent_name="pump", artifacts_dir="/tmp/arts")
    )
    lifecycle_card(subject, FactsExtras())
    provenance_card(subject, FactsExtras())
    assert calls == []


def test_extras_loader_reads_reference_artifacts_chat_and_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "arts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        '{"chat_path": "/tmp/session.json"}', encoding="utf-8"
    )
    monkeypatch.setattr(
        "sase.core.agent_artifact_paths.resolve_agent_artifact_path",
        lambda path: Path(path),
    )
    monkeypatch.setattr(
        "sase.artifact_ref_entries.reference_for_agent_name",
        lambda name: f"@agent:{name}",
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.dismissed_bundles_dir",
        lambda: tmp_path,
    )
    summary = SimpleNamespace(
        dismissed_at="2026-10-08T18:20:00Z",
        revived_at="2026-10-09T09:00:00Z",
        times_revived=3,
        bundle_path=str(tmp_path / "run.json"),
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_bundle_index.query_summaries",
        lambda root, suffixes=None, visibility=None, **_k: [summary],
    )
    subject = record_subject_from_agent(
        _agent(
            agent_name="indexed",
            artifacts_dir=str(artifacts),
            raw_suffix="20261008180600-code",
        )
    )
    extras = load_facts_extras(subject)
    assert extras.reference == "@agent:indexed"
    assert extras.artifacts_dir == str(artifacts)
    assert extras.chat_path == "/tmp/session.json"
    assert extras.dismissed_at == "2026-10-08T18:20:00Z"
    assert extras.revived_at == "2026-10-09T09:00:00Z"
    assert extras.times_revived == 3
    assert extras.bundle_path == str(tmp_path / "run.json")


def test_missing_index_yields_empty_index_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.artifact_ref_entries.reference_for_agent_name",
        lambda name: f"@agent:{name}",
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.dismissed_bundles_dir",
        lambda: Path("/missing-archive-root"),
    )
    monkeypatch.setattr(
        "sase.ace.dismissed_bundle_index.query_summaries",
        lambda *_a, **_k: None,
    )
    extras = load_facts_extras(record_subject_from_agent(_agent(agent_name="gone")))
    assert extras.dismissed_at is None
    assert extras.revived_at is None
    assert extras.times_revived == 0
    assert extras.bundle_path is None
    assert extras.reference == "@agent:gone"
