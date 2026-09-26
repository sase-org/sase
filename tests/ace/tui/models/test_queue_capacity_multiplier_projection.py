"""Focused multiplier projection tests for phase sase-19f.6.1.

Covers Agent state mutual exclusivity plus filesystem, wire, identity, and
dedup projections carrying ``queue_capacity_multiplier``.
"""

from __future__ import annotations

import json
from pathlib import Path

from sase.ace.tui.models._dedup import _merge_agent_fields
from sase.ace.tui.models._loaders._meta_enrichment import (
    enrich_agent_from_meta,
    enrich_agent_from_meta_wire,
)
from sase.ace.tui.models._loaders._meta_enrichment_identity import (
    meta_has_wait_directive,
    wire_meta_has_wait_directive,
)
from sase.core.agent_scan_wire import AgentMetaWire, WaitingMarkerWire
from tests._enrich_agent_helpers import make_agent


def test_set_queue_capacity_multiplier_clears_integer() -> None:
    agent = make_agent()
    agent.set_queue_capacity(5, explicit=True)
    assert agent.queue_capacity == 5
    assert agent.queue_capacity_multiplier is None

    agent.set_queue_capacity(None, multiplier=1.5)
    assert agent.queue_capacity is None
    assert agent.queue_capacity_multiplier == 1.5
    assert agent.wait_runners is None


def test_set_queue_capacity_integer_clears_multiplier() -> None:
    agent = make_agent()
    agent.set_queue_capacity(None, multiplier=1.5)
    assert agent.queue_capacity_multiplier == 1.5

    agent.set_queue_capacity(5, explicit=True)
    assert agent.queue_capacity == 5
    assert agent.queue_capacity_multiplier is None
    assert agent.wait_runners == 5


def test_set_queue_capacity_integer_wins_over_multiplier() -> None:
    agent = make_agent()
    agent.set_queue_capacity(5, explicit=True, multiplier=1.5)
    assert agent.queue_capacity == 5
    assert agent.queue_capacity_multiplier is None


def test_filesystem_meta_multiplier(tmp_path: Path) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"pid": 1234, "queue_capacity_multiplier": 1.5})
    )
    agent = make_agent(status="STARTING")
    enrich_agent_from_meta(agent, str(tmp_path))
    assert agent.queue_capacity is None
    assert agent.queue_capacity_multiplier == 1.5
    assert agent.wait_runners is None


def test_filesystem_waiting_multiplier_over_meta(tmp_path: Path) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"pid": 1234, "queue_capacity": 4, "queue_capacity_explicit": True})
    )
    (tmp_path / "waiting.json").write_text(
        json.dumps({"queue_capacity_multiplier": 1.5})
    )
    agent = make_agent(status="STARTING")
    enrich_agent_from_meta(agent, str(tmp_path))
    assert agent.queue_capacity is None
    assert agent.queue_capacity_multiplier == 1.5


def test_filesystem_integer_wins_over_multiplier(tmp_path: Path) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"pid": 1234, "queue_capacity": 4, "queue_capacity_multiplier": 1.5})
    )
    agent = make_agent(status="STARTING")
    enrich_agent_from_meta(agent, str(tmp_path))
    assert agent.queue_capacity == 4
    assert agent.queue_capacity_multiplier is None


def test_filesystem_invalid_multiplier_ignored(tmp_path: Path) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"pid": 1234, "queue_capacity_multiplier": 0.0})
    )
    agent = make_agent(status="STARTING")
    enrich_agent_from_meta(agent, str(tmp_path))
    assert agent.queue_capacity is None
    assert agent.queue_capacity_multiplier is None


def test_wire_meta_multiplier() -> None:
    agent = make_agent(status="STARTING")
    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(pid=1234, queue_capacity_multiplier=1.5),
        None,
        None,
    )
    assert agent.queue_capacity is None
    assert agent.queue_capacity_multiplier == 1.5


def test_wire_waiting_multiplier_over_meta() -> None:
    agent = make_agent(status="STARTING")
    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(pid=1234, queue_capacity=4, queue_capacity_explicit=True),
        WaitingMarkerWire(queue_capacity_multiplier=1.5),
        None,
    )
    assert agent.queue_capacity is None
    assert agent.queue_capacity_multiplier == 1.5


def test_wire_integer_wins_over_multiplier() -> None:
    agent = make_agent(status="STARTING")
    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(pid=1234, queue_capacity=4, queue_capacity_multiplier=1.5),
        None,
        None,
    )
    assert agent.queue_capacity == 4
    assert agent.queue_capacity_multiplier is None


def test_dedup_copies_multiplier() -> None:
    target = make_agent()
    source = make_agent()
    source.set_queue_capacity(None, multiplier=1.5)
    _merge_agent_fields(target, source)
    assert target.queue_capacity is None
    assert target.queue_capacity_multiplier == 1.5


def test_dedup_integer_wins_over_multiplier() -> None:
    target = make_agent()
    target.set_queue_capacity(4, explicit=True)
    source = make_agent()
    source.set_queue_capacity(None, multiplier=1.5)
    _merge_agent_fields(target, source)
    assert target.queue_capacity == 4
    assert target.queue_capacity_multiplier is None


def test_identity_wait_directive_sees_multiplier() -> None:
    assert meta_has_wait_directive({"queue_capacity_multiplier": 1.5}) is True
    assert (
        wire_meta_has_wait_directive(
            AgentMetaWire(pid=1, queue_capacity_multiplier=1.5)
        )
        is True
    )
