from __future__ import annotations

from sase.artifact_links.read_candidates import rank_read_citation_candidates
from sase.artifact_read_log import ARTIFACT_READ_LOG_SCHEMA_VERSION, ArtifactReadEvent


def _event(
    *,
    ref: str,
    agent_name: str,
    reason: str,
    timestamp: str,
) -> ArtifactReadEvent:
    return ArtifactReadEvent(
        schema_version=ARTIFACT_READ_LOG_SCHEMA_VERSION,
        id=f"{agent_name}-{ref}-{timestamp}",
        timestamp=timestamp,
        project="proj",
        cwd="/tmp/proj",
        ref=ref,
        reason=reason,
        agent_name=agent_name,
        agent_source="SASE_AGENT_NAME",
        artifacts_dir=None,
        recorded_link=False,
    )


def test_aggregates_reads_by_agent_and_ref() -> None:
    events = (
        _event(
            ref="plan:202608/x.md",
            agent_name="alice.athena.worker",
            reason="first look",
            timestamp="2026-08-01T00:00:00Z",
        ),
        _event(
            ref="plan:202608/x.md",
            agent_name="alice.athena.worker",
            reason="second look",
            timestamp="2026-08-02T00:00:00Z",
        ),
        _event(
            ref="research:202608/y.md",
            agent_name="bob.athena.worker",
            reason="context",
            timestamp="2026-08-01T00:00:00Z",
        ),
    )

    candidates = rank_read_citation_candidates(events)

    assert len(candidates) == 2
    top = candidates[0]
    assert top.agent_name == "alice.athena.worker"
    assert top.ref == "plan:202608/x.md"
    assert top.reads == 2
    assert top.reason == "second look"
    assert top.latest_timestamp == "2026-08-02T00:00:00Z"


def test_scoped_to_every_read_not_just_plan_or_research() -> None:
    events = (
        _event(
            ref="agent:someone.athena.worker",
            agent_name="alice.athena.worker",
            reason="checking on a teammate",
            timestamp="2026-08-01T00:00:00Z",
        ),
    )

    candidates = rank_read_citation_candidates(events)

    assert len(candidates) == 1
    assert candidates[0].ref == "agent:someone.athena.worker"


def test_empty_input_yields_no_candidates() -> None:
    assert rank_read_citation_candidates(()) == ()
