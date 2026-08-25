"""Tests for legacy glossary read-event parsing and summaries."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from sase.memory.legacy_glossary_read_log import (
    GlossaryReadError,
    GlossaryReadEvent,
    filter_glossary_read_events,
    glossary_read_log_path,
    normalize_read_reason,
    read_glossary_read_events,
    summarize_glossary_reads_by_agent,
    summarize_glossary_reads_by_term,
)


def test_normalize_read_reason_rejects_blank() -> None:
    assert normalize_read_reason("  Need hood  ") == "Need hood"
    with pytest.raises(GlossaryReadError, match="must not be empty"):
        normalize_read_reason("   ")


def test_read_round_trip_skips_malformed_and_wrong_schema(
    tmp_path: Path,
) -> None:
    event = _event()
    log_path = tmp_path / "glossary_reads.jsonl"

    _write_events(log_path, event)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("not json\n")
        handle.write(json.dumps({"schema_version": 2, "id": "other"}) + "\n")
        handle.write(json.dumps({"schema_version": 1, "id": "missing-fields"}) + "\n")

    assert read_glossary_read_events(log_path=log_path) == (event,)


def test_read_missing_log_returns_empty(tmp_path: Path) -> None:
    assert read_glossary_read_events(log_path=tmp_path / "missing.jsonl") == ()


def test_multiple_legacy_rows_are_all_readable(tmp_path: Path) -> None:
    log_path = tmp_path / "glossary_reads.jsonl"
    events = tuple(_event(id=f"read-{index:02d}") for index in range(20))

    _write_events(log_path, *events)

    read = read_glossary_read_events(log_path=log_path)
    assert sorted(item.id for item in read) == sorted(item.id for item in events)
    assert all(isinstance(item, GlossaryReadEvent) for item in read)


def test_glossary_read_log_path_uses_project_state_and_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sase.memory.legacy_glossary_read_log.sase_projects_dir",
        lambda: tmp_path / ".sase" / "projects",
    )
    monkeypatch.setattr(
        "sase.memory.legacy_glossary_read_log.resolve_project_alias_ref",
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


def _write_events(path: Path, *events: GlossaryReadEvent) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            json.dump(
                {
                    "schema_version": event.schema_version,
                    "id": event.id,
                    "timestamp": event.timestamp,
                    "project": event.project,
                    "cwd": event.cwd,
                    "agent_name": event.agent_name,
                    "agent_source": event.agent_source,
                    "artifacts_dir": event.artifacts_dir,
                    "reason": event.reason,
                    "terms": list(event.terms),
                    "related_terms": list(event.related_terms),
                    "depth_limit": event.depth_limit,
                    "definition_bytes": event.definition_bytes,
                    "source_path": event.source_path,
                },
                handle,
                sort_keys=True,
            )
            handle.write("\n")
