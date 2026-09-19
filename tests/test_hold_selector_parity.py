"""Selector-parity: CLI/directive expansion, tribe identity, and admission."""

from __future__ import annotations

from dataclasses import replace

import pytest

from sase.ace.tui.models.agent_runner_slots import _capacity_record_from_agent
from sase.core.agent_hold_facade import (
    _hold_selectors_wire,
    agent_hold_blocks_candidate,
    arm_agent_hold,
)
from sase.core.agent_hold_identity import apply_hold_identity_to_capacity_records
from sase.core.agent_scan_wire import AgentMetaWire
from sase.core.runner_slots._admission_capacity_records import (
    capacity_record_from_scan,
)
from sase.xprompt.hold_directive import HoldFields, hold_fields_to_selectors

from tests.ace.tui._agent_runner_slots_helpers import _agent
from tests._runner_slots_helpers import _always_live, _record

pytest.importorskip("sase_core_rs")


def _cli_armer(**overrides: object) -> dict[str, object]:
    armer: dict[str, object] = {
        "kind": "cli",
        "key": "cli:review",
        "display": "review",
        "project": "proj",
        "pid": 4242,
    }
    armer.update(overrides)
    return armer


def test_cli_and_directive_family_selectors_both_block_role_suffixed_names() -> None:
    cli = arm_agent_hold(
        armer=_cli_armer(key="cli:family"),
        names=["team"],
        scope="host",
        ttl_seconds=60,
        now=1_000.0,
    ).record
    directive = arm_agent_hold(
        armer=_cli_armer(key="cli:directive"),
        selectors=hold_fields_to_selectors(HoldFields(names=("team",))),
        scope="host",
        ttl_seconds=60,
        now=1_000.0,
    ).record
    candidate = {
        "project": "proj",
        "created_at": 999.0,
        "agent_name": "team--code",
        "family": "team",
    }
    assert agent_hold_blocks_candidate(cli, candidate) is not None
    assert agent_hold_blocks_candidate(directive, candidate) is not None
    assert cli["selectors"]["families"] == ["team"]
    assert directive["selectors"]["families"] == ["team"]


def test_role_suffixed_cli_name_stays_exact() -> None:
    selectors = _hold_selectors_wire(names=["team--code"])
    assert selectors["names"] == ["team--code"]
    assert selectors["families"] == []
    record = arm_agent_hold(
        armer=_cli_armer(key="cli:exact"),
        names=["team--code"],
        scope="host",
        ttl_seconds=60,
        now=1_000.0,
    ).record
    matching = {
        "project": "proj",
        "created_at": 999.0,
        "agent_name": "team--code",
        "family": "team",
    }
    other_role = {
        "project": "proj",
        "created_at": 999.0,
        "agent_name": "team--plan",
        "family": "team",
    }
    assert agent_hold_blocks_candidate(record, matching) is not None
    assert agent_hold_blocks_candidate(record, other_role) is None


def test_public_job_selector_keeps_independently_stored_job_tribe() -> None:
    fields = HoldFields(tribes=("job",))
    automation = hold_fields_to_selectors(
        fields, identity={"stored_tribes": [], "layers": []}
    )
    independent = hold_fields_to_selectors(
        fields, identity={"stored_tribes": ["job"], "layers": []}
    )
    assert automation["tribes"] == ["chop"]
    assert independent["tribes"] == ["job"]


def test_admission_overlay_honors_posthoc_tribe_and_clan_generation() -> None:
    timestamp = "20260918120000"
    scan = replace(
        _record(f"/proj/{timestamp}", pid=9),
        agent_meta=AgentMetaWire(
            name="target",
            cl_name="cl",
            agent_clan="builders",
            agent_clan_generation="gen-1",
            clan_tribe="stale",
        ),
        timestamp=timestamp,
    )
    sibling = replace(
        _record(f"/proj/{timestamp}2", pid=10),
        agent_meta=AgentMetaWire(
            name="sibling",
            cl_name="other",
            agent_clan="builders",
            agent_clan_generation="gen-1",
            clan_tribe="epic",
        ),
        timestamp=f"{timestamp}2",
    )
    records = [
        capacity_record_from_scan(scan, _always_live),
        capacity_record_from_scan(sibling, _always_live),
    ]
    apply_hold_identity_to_capacity_records(
        records,
        scan_records=[scan, sibling],
        stored_assignments={("run", "cl", timestamp): "ops"},
    )
    target, other = records
    assert target["tribe"] == "ops"
    assert set(target["tribes"]) == {"epic", "ops"}
    assert other["tribe"] == "epic"
    assert other["tribes"] == ["epic"]


def test_tui_and_scan_capacity_records_share_effective_tribe_membership() -> None:
    timestamp = "20260918120000"
    scan = replace(
        _record(f"/proj/{timestamp}", pid=9),
        agent_meta=AgentMetaWire(
            name="target",
            cl_name="cl",
            agent_clan="builders",
            agent_clan_generation="gen-1",
            clan_tribe="stale",
        ),
        timestamp=timestamp,
    )
    sibling = replace(
        _record(f"/proj/{timestamp}2", pid=10),
        agent_meta=AgentMetaWire(
            name="sibling",
            cl_name="other",
            agent_clan="builders",
            agent_clan_generation="gen-1",
            clan_tribe="epic",
        ),
        timestamp=f"{timestamp}2",
    )
    scan_record = capacity_record_from_scan(scan, _always_live)
    sibling_record = capacity_record_from_scan(sibling, _always_live)
    apply_hold_identity_to_capacity_records(
        [scan_record, sibling_record],
        scan_records=[scan, sibling],
        stored_assignments={("run", "cl", timestamp): "ops"},
    )
    member = _agent(
        "target",
        cl_name="cl",
        raw_suffix=timestamp,
        artifacts_dir=f"/proj/{timestamp}",
        agent_name="target",
        agent_clan="builders",
        agent_clan_generation="gen-1",
        tribe="ops",
        clan_tribe="stale",
    )
    container = _agent(
        "builders",
        is_clan_container=True,
        agent_clan="builders",
        agent_clan_generation="gen-1",
        clan_tribe="epic",
        clan_tribes=("epic",),
    )
    tui_record = _capacity_record_from_agent(
        member, {}, clan_containers={("builders", "gen-1"): container}
    )
    assert set(scan_record["tribes"]) == {"epic", "ops"}
    assert set(tui_record["tribes"]) == {"epic", "ops"}
    assert scan_record["tribe"] == tui_record["tribe"] == "ops"
