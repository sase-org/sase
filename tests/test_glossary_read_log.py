"""Tests for the glossary read-event store and summaries."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from sase.agent.identity import AgentIdentity, AgentIdentityError
from sase.glossary.read_log import (
    GlossaryReadError,
    GlossaryReadEvent,
    append_glossary_read_event,
    build_glossary_read_event,
    filter_glossary_read_events,
    glossary_read_log_path,
    normalize_read_reason,
    read_glossary_read_events,
    require_agent_identity,
    summarize_glossary_reads_by_agent,
    summarize_glossary_reads_by_term,
)


def test_normalize_read_reason_rejects_blank() -> None:
    assert normalize_read_reason("  Need hood  ") == "Need hood"
    with pytest.raises(GlossaryReadError, match="must not be empty"):
        normalize_read_reason("   ")


def test_require_agent_identity_raises_without_attribution() -> None:
    with pytest.raises(AgentIdentityError, match="glossary reads"):
        require_agent_identity({})


def test_append_and_read_round_trip_skips_malformed_and_wrong_schema(
    tmp_path: Path,
) -> None:
    event = _event()
    log_path = tmp_path / "glossary_reads.jsonl"

    append_glossary_read_event(event, log_path=log_path)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("not json\n")
        handle.write(json.dumps({"schema_version": 2, "id": "other"}) + "\n")
        handle.write(json.dumps({"schema_version": 1, "id": "missing-fields"}) + "\n")

    assert read_glossary_read_events(log_path=log_path) == (event,)


def test_read_missing_log_returns_empty(tmp_path: Path) -> None:
    assert read_glossary_read_events(log_path=tmp_path / "missing.jsonl") == ()


def test_concurrent_appends_are_all_readable(tmp_path: Path) -> None:
    log_path = tmp_path / "glossary_reads.jsonl"
    events = tuple(_event(id=f"read-{index:02d}") for index in range(20))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(
            pool.map(
                lambda event: append_glossary_read_event(event, log_path=log_path),
                events,
            )
        )

    read = read_glossary_read_events(log_path=log_path)
    assert sorted(item.id for item in read) == sorted(item.id for item in events)
    assert all(isinstance(item, GlossaryReadEvent) for item in read)


def test_glossary_read_log_path_uses_project_state_and_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sase.glossary.read_log.sase_projects_dir",
        lambda: tmp_path / ".sase" / "projects",
    )
    monkeypatch.setattr(
        "sase.glossary.read_log.resolve_project_alias_ref",
        lambda ref: {"bob": "bob-cli"}.get(ref, ref),
    )

    assert glossary_read_log_path("proj") == (
        tmp_path / ".sase" / "projects" / "proj" / "glossary_reads.jsonl"
    )
    assert glossary_read_log_path("bob") == (
        tmp_path / ".sase" / "projects" / "bob-cli" / "glossary_reads.jsonl"
    )


def test_filter_and_summaries_cover_requested_and_related_terms() -> None:
    base = _event()
    second = replace(
        base,
        id="read-b",
        timestamp="2026-05-23T12:01:00+00:00",
        agent_name="agent-b",
        reason="Second",
        terms=("Stitch",),
        related_terms=(),
        definition_bytes=10,
    )
    third = replace(
        base,
        id="read-c",
        timestamp="2026-05-23T12:02:00+00:00",
        reason="Third",
        terms=("Agent Hood",),
        related_terms=("Sase Agent",),
    )

    filtered = filter_glossary_read_events(
        [base, second, third],
        term="agent-hood",
        agent_name="agent-a",
    )
    assert filtered == (base, third)

    related_hits = filter_glossary_read_events([base, second, third], term="sase agent")
    assert related_hits == (base, third)

    term_summaries = summarize_glossary_reads_by_term([base, second, third])
    agent_summaries = summarize_glossary_reads_by_agent([base, second, third])

    by_term = {summary.term: summary for summary in term_summaries}
    assert by_term["Agent Hood"].read_count == 2
    assert by_term["Agent Hood"].distinct_agent_count == 1
    assert by_term["Agent Hood"].last_reason == "Third"
    assert by_term["Sase Agent"].read_count == 2
    assert by_term["Stitch"].read_count == 1
    assert by_term["Stitch"].last_agent == "agent-b"

    assert agent_summaries[0].agent_name == "agent-a"
    assert agent_summaries[0].read_count == 2
    assert agent_summaries[0].distinct_term_count == 2
    assert agent_summaries[0].last_term == "Agent Hood"
    assert agent_summaries[1].agent_name == "agent-b"
    assert agent_summaries[1].read_count == 1


def test_build_glossary_read_event_records_canonical_fields(tmp_path: Path) -> None:
    event = build_glossary_read_event(
        reason="  Need hood ",
        agent=AgentIdentity("agent-a", "SASE_AGENT_NAME", "/tmp/artifacts"),
        terms=("Agent Hood",),
        related_terms=("Sase Agent",),
        depth_limit=1,
        definition_bytes=64,
        source_path="/repo/sase/sase.yml",
        project="proj",
        cwd=tmp_path,
        now=datetime(2026, 5, 23, 12, 0, tzinfo=UTC),
        read_id="read-a",
    )

    assert event.reason == "Need hood"
    assert event.terms == ("Agent Hood",)
    assert event.related_terms == ("Sase Agent",)
    assert event.depth_limit == 1
    assert event.definition_bytes == 64
    assert event.source_path == "/repo/sase/sase.yml"
    assert event.project == "proj"
    assert event.timestamp == "2026-05-23T12:00:00+00:00"


def _event(**overrides: object) -> GlossaryReadEvent:
    payload: dict[str, object] = {
        "schema_version": 1,
        "id": "read-a",
        "timestamp": "2026-05-23T12:00:00+00:00",
        "project": "proj",
        "cwd": "/tmp",
        "agent_name": "agent-a",
        "agent_source": "SASE_AGENT_NAME",
        "artifacts_dir": "/tmp/artifacts",
        "reason": "Need hood",
        "terms": ("Agent Hood",),
        "related_terms": ("Sase Agent",),
        "depth_limit": None,
        "definition_bytes": 42,
        "source_path": "/repo/sase/sase.yml",
    }
    payload.update(overrides)
    return GlossaryReadEvent(**payload)  # type: ignore[arg-type]
