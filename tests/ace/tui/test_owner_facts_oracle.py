"""Production oracle: owner loader vs gateway-catalog per-identity facts."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from sase.ace.tui.models._agent_status_apply import apply_status_overrides
from sase.ace.tui.models._agent_status_roles import agent_family_role
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_loader import load_tiered_agents
from sase.ace.tui.models.agent_panels import (
    agents_for_panel,
    effective_tribe_per_agent,
    panel_keys_for,
)
from sase.ace.tui.models.fleet_agents import project_fleet_agents
from sase.agent.status_buckets import agent_status_bucket
from sase.core import time as core_time
from sase.core.rust import require_rust_binding

from tests.ace.tui.fleet_fixture import fleet_host_response
from tests.ace.tui.owner_roster_fixture import (
    OwnerRosterFixture,
    write_owner_roster_fixture,
)

# Rows whose identity is a bare owner record; nested shells are compared too.
_FACT_IDENTITIES = (
    "lane",
    "lane--plan",
    "lane--code",
    "lane--mon",
    "lane--gate",
    "lane--proc",
    "lane--gate-pending",
    "settled",
    "settled--code",
    "fresh-launch",
    "tale-fam",
    "tale-fam--plan",
    "tale-fam--code",
    "epic-fam",
    "epic-fam--plan",
    "epic-fam--epic",
    "active-fam",
    "active-fam--plan",
    "active-fam--code",
    "wait-fam",
    "review-plan",
    "answering",
    "asker",
    "asker--ask",
    "asker--code",
)

_DIMENSIONS: dict[str, Callable[[Agent], object]] = {
    "status": lambda a: a.status,
    "status_bucket": agent_status_bucket,
    "agent_family_role": agent_family_role,
    "role_suffix": lambda a: a.role_suffix,
    "clan_tribe": lambda a: a.clan_tribe,
    # proc ids are registry-backed on the owner side; only monitor/gate chips
    # are persisted in the artifact record.
    "shell_ids": lambda a: (a.monitor_id, a.gate_id),
    "shell_state": lambda a: (a.monitor_state, a.gate_state, a.gate_kind),
    "run_start_time": lambda a: _minute(a.run_start_time),
    "stop_time": lambda a: _minute(a.stop_time),
}


def _minute(value: Any) -> Any:
    """Compare wall times at second resolution, ignoring tz-awareness."""
    if value is None:
        return None
    return value.replace(tzinfo=None, microsecond=0)


@pytest.fixture
def fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> OwnerRosterFixture:
    # The catalog reads artifact-directory stamps as UTC; pin the configured
    # zone to UTC so owner and catalog wall times are comparable.
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    monkeypatch.setattr(core_time, "_cached_timezone", ZoneInfo("UTC"))
    built = write_owner_roster_fixture(tmp_path)
    monkeypatch.setenv("SASE_HOME", str(built.home))
    return built


def _owner_rows(built: OwnerRosterFixture) -> dict[str, Agent]:
    agents, _state = load_tiered_agents(index_freshness="revalidate")
    apply_status_overrides(agents, classify_diff_badges=False)
    return _by_name(agents)


def _by_name(agents: list[Agent]) -> dict[str, Agent]:
    return {agent.agent_name: agent for agent in agents if agent.agent_name}


def _assemble(
    built: OwnerRosterFixture, *, compact: bool, **extra: object
) -> dict[str, Any]:
    assemble = require_rust_binding("assemble_fleet_catalog")
    return assemble(
        {
            "sase_home": str(built.home),
            "agents_list_projection": compact,
            "observations": built.observations,
            **extra,
        }
    )


def _remote_agents(payload: dict[str, Any]) -> list[Agent]:
    summaries = payload["summaries"]
    installation = summaries[0]["logical_locator"]["project"]["origin"][
        "installation_id"
    ]
    response = fleet_host_response(summaries=summaries, installation_id=installation)
    return list(project_fleet_agents(catalog_response=response).fleet_rows)


def _remote_rows(built: OwnerRosterFixture, *, compact: bool) -> list[Agent]:
    return _remote_agents(_assemble(built, compact=compact))


@pytest.mark.parametrize("compact", [False, True], ids=["current", "compact-index"])
@pytest.mark.parametrize("dimension", sorted(_DIMENSIONS))
def test_owner_and_catalog_agree_per_identity_and_dimension(
    fixture: OwnerRosterFixture, compact: bool, dimension: str
) -> None:
    owner = _owner_rows(fixture)
    remote = _by_name(_remote_rows(fixture, compact=compact))
    read = _DIMENSIONS[dimension]
    # A row the owner never recorded a run start for falls back to its start
    # time on the viewer; only a recorded run start is an owner fact.
    optional = dimension == "run_start_time"
    mismatches = {
        name: (read(owner[name]), read(remote[name]))
        for name in _FACT_IDENTITIES
        if name in owner
        and name in remote
        and read(owner[name]) != read(remote[name])
        and not (optional and read(owner[name]) is None)
    }
    assert mismatches == {}, f"{dimension} owner-vs-remote: {mismatches}"


def _start_times(rows: list[Agent]) -> dict[str, object]:
    # The catalog gives every family member its root's start (an existing
    # presentation rule), so the per-row start time is only comparable for
    # roots and standalone rows.
    return {
        row.agent_name: _minute(row.start_time)
        for row in rows
        if row.agent_name and not row.parent_timestamp
    }


def _tribes(rows: list[Agent]) -> dict[str, object]:
    """Direct and inherited tribe as the panel grouping resolves them."""
    return dict(
        zip(
            (row.agent_name for row in rows),
            effective_tribe_per_agent(rows),
            strict=True,
        )
    )


@pytest.mark.parametrize("compact", [False, True], ids=["current", "compact-index"])
@pytest.mark.parametrize("dimension", ["start_time", "tribe"])
def test_owner_and_catalog_agree_on_root_time_and_effective_tribe(
    fixture: OwnerRosterFixture, compact: bool, dimension: str
) -> None:
    agents, _state = load_tiered_agents(index_freshness="revalidate")
    apply_status_overrides(agents, classify_diff_badges=False)
    read = _start_times if dimension == "start_time" else _tribes
    owner = read(agents)
    remote = read(_remote_rows(fixture, compact=compact))
    mismatches = {
        name: (owner[name], remote[name])
        for name in _FACT_IDENTITIES
        if name in owner and name in remote and owner[name] != remote[name]
    }
    assert mismatches == {}, f"{dimension} owner-vs-remote: {mismatches}"


def _parent_names(rows: list[Agent]) -> dict[str, str | None]:
    """Map each identity to its parent's name, resolving either key spelling."""
    owners = {}
    for row in rows:
        for key in (row.raw_suffix, row.fleet_exact_key):
            if key:
                owners[key] = row.agent_name
    return {
        row.agent_name: owners.get(row.parent_timestamp)
        if row.parent_timestamp
        else None
        for row in rows
        if row.agent_name
    }


@pytest.mark.parametrize("compact", [False, True], ids=["current", "compact-index"])
def test_owner_and_catalog_agree_on_parent_nesting(
    fixture: OwnerRosterFixture, compact: bool
) -> None:
    agents, _state = load_tiered_agents(index_freshness="revalidate")
    apply_status_overrides(agents, classify_diff_badges=False)
    owner = _parent_names(agents)
    remote = _parent_names(_remote_rows(fixture, compact=compact))
    mismatches = {
        name: (owner[name], remote[name])
        for name in _FACT_IDENTITIES
        if name in owner and name in remote and owner[name] != remote[name]
    }
    assert mismatches == {}, f"parent_timestamp owner-vs-remote: {mismatches}"


@pytest.mark.parametrize("compact", [False, True], ids=["current", "compact-index"])
def test_owner_and_catalog_agree_on_identity_set_and_panels(
    fixture: OwnerRosterFixture, compact: bool
) -> None:
    owner_rows = list(_owner_rows(fixture).values())
    remote_rows = _remote_rows(fixture, compact=compact)
    owner_names = {a.agent_name for a in owner_rows}
    remote_names = {a.agent_name for a in remote_rows}
    assert set(_FACT_IDENTITIES) <= owner_names
    assert set(_FACT_IDENTITIES) <= remote_names

    def panels(rows: list[Agent]) -> dict[str, int]:
        return {
            "@default" if key is None else key: len(
                [
                    row
                    for row in agents_for_panel(rows, key)
                    if row.agent_name in _FACT_IDENTITIES and not row.parent_timestamp
                ]
            )
            for key in panel_keys_for(rows)
        }

    assert panels(remote_rows) == panels(owner_rows)


def test_tale_and_epic_families_carry_rich_status_without_bare_plan_rows(
    fixture: OwnerRosterFixture,
) -> None:
    remote = _by_name(_remote_rows(fixture, compact=False))
    assert remote["tale-fam"].status.startswith("TALE DONE")
    assert remote["epic-fam"].status.startswith("EPIC CREATED")
    for name in ("tale-fam--plan", "epic-fam--plan"):
        shell = remote[name]
        assert shell.parent_timestamp, f"{name} is an unparented row"
        assert shell.gate_id is not None


def test_active_and_waiting_families_and_answered_question(
    fixture: OwnerRosterFixture,
) -> None:
    remote = _by_name(_remote_rows(fixture, compact=False))
    assert remote["active-fam"].status in {"WORKING TALE", "WORKING PLAN"}
    assert remote["wait-fam"].status == "WAITING"
    assert remote["answering"].status == "ANSWERED"
    assert remote["review-plan"].status == "TALE"


def test_injected_owner_observations_replace_host_reads(
    fixture: OwnerRosterFixture,
) -> None:
    """Hermetic injection decides tier/answered without reading the host."""
    injected = _by_name(
        _remote_agents(
            _assemble(
                fixture,
                compact=False,
                owner_files={
                    "question_answered": [],
                    "plan_tiers": {"review-plan": "epic"},
                },
            )
        )
    )
    assert injected["review-plan"].status == "EPIC"
    assert injected["answering"].status == "QUESTION"


def test_legacy_summary_without_presentation_projects_degraded_rows(
    fixture: OwnerRosterFixture,
) -> None:
    payload = _assemble(fixture, compact=False)
    for summary in payload["summaries"]:
        summary.pop("presentation", None)
    rows = _remote_agents(payload)
    assert rows, "legacy payload projected no rows"
    by_name = _by_name(rows)
    assert by_name["tale-fam"].plan_action is None
    assert by_name["tale-fam--plan"].gate_id


def _rendered(agent: Agent, now: Any) -> tuple[str, str]:
    """Render one row and keep the fact-bearing text: status, chips, and stamp.

    The project label, the machine/type tag, the row's display name, and live
    elapsed durations are viewer- or fixture-specific and are asserted by the
    per-dimension oracle above, so they are dropped from the visual comparison.
    """
    from sase.ace.tui.widgets._agent_list_render_agent import format_agent_option

    left, suffix, _ = format_agent_option(agent, 0, is_selected=False, now=now)
    match = re.search(r"\(([^)]*)\)((?: [^\w\s(]\S*)*)", left.plain)
    status_and_chips = (match.group(1), match.group(2)) if match else None
    stamp = re.match(r"[A-Z][a-z]{2} \d+ '\d+", suffix.plain)
    return repr(status_and_chips), stamp.group(0) if stamp else "running"


@pytest.mark.parametrize("compact", [False, True], ids=["current", "compact-index"])
def test_owner_and_catalog_render_equal_rows_and_nested_shell_counts(
    fixture: OwnerRosterFixture, compact: bool
) -> None:
    from datetime import datetime

    owner = _owner_rows(fixture)
    remote_rows = _remote_rows(fixture, compact=compact)
    remote = _by_name(remote_rows)
    now = datetime(2030, 1, 1)

    mismatches = {
        name: (_rendered(owner[name], now), _rendered(remote[name], now))
        for name in _FACT_IDENTITIES
        if name in owner
        and name in remote
        and _rendered(owner[name], now) != _rendered(remote[name], now)
    }
    assert mismatches == {}, f"rendered owner-vs-remote: {mismatches}"

    def nested(rows: dict[str, Agent]) -> int:
        return len(
            [n for n in _FACT_IDENTITIES if n in rows and rows[n].parent_timestamp]
        )

    assert nested(remote) == nested(owner)
