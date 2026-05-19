"""Tests for pending-question metadata enrichment."""

import json
from pathlib import Path

from sase.ace.tui.models._loaders._meta_enrichment import (
    enrich_agent_from_meta,
    enrich_agent_from_meta_wire,
)
from sase.core.agent_scan_wire import AgentMetaWire, PendingQuestionMarkerWire
from tests._enrich_agent_helpers import make_agent


def test_pending_question_marker_flips_running_to_question(tmp_path: Path) -> None:
    """pending_question.json marker flips a RUNNING agent to QUESTION."""
    (tmp_path / "agent_meta.json").write_text(json.dumps({"pid": 1234}))
    (tmp_path / "pending_question.json").write_text(
        json.dumps({"session_id": "abc", "request_path": "/x", "submitted_at": "t"})
    )

    agent = make_agent(status="RUNNING")
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.status == "QUESTION"


def test_pending_question_marker_flips_starting_to_question(tmp_path: Path) -> None:
    """pending_question.json marker overrides a pre-run STARTING row."""
    (tmp_path / "agent_meta.json").write_text(json.dumps({"pid": 1234}))
    (tmp_path / "pending_question.json").write_text(
        json.dumps({"session_id": "abc", "request_path": "/x", "submitted_at": "t"})
    )

    agent = make_agent(status="STARTING")
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.status == "QUESTION"


def test_pending_question_marker_no_op_when_absent(tmp_path: Path) -> None:
    """Without the marker, status stays RUNNING."""
    (tmp_path / "agent_meta.json").write_text(json.dumps({"pid": 1234}))

    agent = make_agent(status="RUNNING")
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.status == "RUNNING"


def test_question_response_metadata_populates_from_filesystem_meta(
    tmp_path: Path,
) -> None:
    """Question request/response paths are preserved on the Agent model."""
    (tmp_path / "agent_meta.json").write_text(
        json.dumps(
            {
                "pid": 1234,
                "question_request_path": "/tmp/question_request.json",
                "question_response_path": "/tmp/question_response.json",
                "question_session_id": "session-1",
            }
        )
    )

    agent = make_agent(status="RUNNING")
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.question_request_path == "/tmp/question_request.json"
    assert agent.question_response_path == "/tmp/question_response.json"
    assert agent.question_session_id == "session-1"


def test_pending_question_marker_does_not_override_done(tmp_path: Path) -> None:
    """A stale marker next to a DONE agent must NOT downgrade the status."""
    (tmp_path / "agent_meta.json").write_text(json.dumps({"pid": 1234}))
    (tmp_path / "pending_question.json").write_text(
        json.dumps({"session_id": "abc", "request_path": "/x", "submitted_at": "t"})
    )

    agent = make_agent(status="DONE")
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.status == "DONE"


def test_pending_question_marker_does_not_override_waiting(tmp_path: Path) -> None:
    """The WAITING override runs first; QUESTION only fires for active rows."""
    (tmp_path / "agent_meta.json").write_text(json.dumps({"pid": 1234}))
    (tmp_path / "waiting.json").write_text(
        json.dumps({"waiting_for": ["dep"], "wait_duration": 300.0})
    )
    (tmp_path / "pending_question.json").write_text(
        json.dumps({"session_id": "abc", "request_path": "/x", "submitted_at": "t"})
    )

    agent = make_agent(status="RUNNING")
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.status == "WAITING"


def test_pending_question_marker_wire_flips_running_to_question() -> None:
    """Snapshot enrichment mirrors filesystem pending_question handling."""
    agent = make_agent(status="RUNNING")
    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(),
        None,
        PendingQuestionMarkerWire(session_id="abc"),
    )
    assert agent.status == "QUESTION"


def test_pending_question_marker_wire_flips_starting_to_question() -> None:
    """Snapshot pending-question markers override STARTING rows."""
    agent = make_agent(status="STARTING")
    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(),
        None,
        PendingQuestionMarkerWire(session_id="abc"),
    )
    assert agent.status == "QUESTION"


def test_pending_question_marker_wire_no_op_when_absent() -> None:
    """Without the marker the wire enricher leaves status alone."""
    agent = make_agent(status="RUNNING")
    enrich_agent_from_meta_wire(agent, AgentMetaWire(), None, None)
    assert agent.status == "RUNNING"


def test_question_response_metadata_populates_from_wire_meta() -> None:
    """Snapshot enrichment mirrors filesystem question metadata handling."""
    agent = make_agent(status="RUNNING")
    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(
            question_request_path="/tmp/question_request.json",
            question_response_path="/tmp/question_response.json",
            question_session_id="session-1",
        ),
        None,
        None,
    )

    assert agent.question_request_path == "/tmp/question_request.json"
    assert agent.question_response_path == "/tmp/question_response.json"
    assert agent.question_session_id == "session-1"


def test_pending_question_marker_wire_does_not_override_done() -> None:
    """A stale wire marker next to a DONE agent must not downgrade status."""
    agent = make_agent(status="DONE")
    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(),
        None,
        PendingQuestionMarkerWire(session_id="abc"),
    )
    assert agent.status == "DONE"
