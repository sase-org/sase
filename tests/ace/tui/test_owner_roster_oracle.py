"""Production oracle: owner loader vs catalog assembly identity signatures."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest

from sase.ace.tui.models._family_shell_membership import _is_concrete_family_shell
from sase.ace.tui.models._fold_filter import filter_agents_by_fold_state
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_loader import load_tiered_agents
from sase.ace.tui.models.agent_panels import agents_for_panel, panel_keys_for
from sase.ace.tui.models.fleet_agents import project_fleet_agents
from sase.ace.tui.models.fold_state import FoldStateManager
from sase.core.rust import require_rust_binding

from tests.ace.tui.fleet_fixture import fleet_host_response
from tests.ace.tui.owner_roster_fixture import write_owner_roster_fixture


def test_owner_roster_oracle_compact_and_current_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = write_owner_roster_fixture(tmp_path)
    monkeypatch.setenv("SASE_HOME", str(fixture.home))

    owner_agents, _state = load_tiered_agents(index_freshness="revalidate")
    owner_sig = _owner_signatures(owner_agents)
    _assert_required_fixture_identities(owner_sig)

    current = _catalog_signatures(
        fixture.home,
        fixture.observations,
        agents_list_projection=False,
    )
    compact = _catalog_signatures(
        fixture.home,
        fixture.observations,
        agents_list_projection=True,
    )
    _assert_equal_signatures("current", owner_sig, current)
    _assert_equal_signatures("compact-index", owner_sig, compact)


def _catalog_signatures(
    home: Path,
    observations: dict[str, str],
    *,
    agents_list_projection: bool,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[tuple[str, tuple[str, ...]], ...]]:
    """Signatures of the rows the viewer builds from the real catalog payload.

    The payload goes through the viewer's own projection, so nesting and
    grouping are decided by the shared Python classifiers rather than by a
    second, catalog-only reading of the summaries.
    """
    assemble = require_rust_binding("assemble_fleet_catalog")
    payload = assemble(
        {
            "sase_home": str(home),
            "agents_list_projection": agents_list_projection,
            "observations": observations,
        }
    )
    summaries = list(payload.get("summaries") or [])
    installation = summaries[0]["logical_locator"]["project"]["origin"][
        "installation_id"
    ]
    response = fleet_host_response(summaries=summaries, installation_id=installation)
    rows = list(project_fleet_agents(catalog_response=response).fleet_rows)
    return _owner_signatures(rows)


def _owner_signatures(
    agents: list[Agent],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[tuple[str, tuple[str, ...]], ...]]:
    visible_rows, _counts = filter_agents_by_fold_state(agents, FoldStateManager())
    nested = tuple(
        sorted(_agent_label(agent) for agent in agents if _owner_is_nested(agent))
    )
    visible = tuple(
        sorted(
            _agent_label(agent) for agent in visible_rows if not _owner_is_nested(agent)
        )
    )
    grouping: list[tuple[str, tuple[str, ...]]] = []
    for key in panel_keys_for(visible_rows):
        members = tuple(
            sorted(
                _agent_label(agent)
                for agent in agents_for_panel(visible_rows, key)
                if not _owner_is_nested(agent)
            )
        )
        grouping.append((_panel_key(key), members))
    return visible, nested, tuple(grouping)


def _owner_is_nested(agent: Agent) -> bool:
    return bool(agent.parent_timestamp) or _is_concrete_family_shell(agent)


def _agent_label(agent: Agent) -> str:
    return agent.agent_name or agent.raw_suffix or agent.cl_name


def _panel_key(key: str | None) -> str:
    return "@default" if key is None else key


def _assert_equal_signatures(
    path: str,
    owner: tuple[object, ...],
    catalog: tuple[object, ...],
) -> None:
    owner_visible, owner_nested, owner_group = owner
    catalog_visible, catalog_nested, catalog_group = catalog
    extra_visible = _diff(catalog_visible, owner_visible)
    missing_visible = _diff(owner_visible, catalog_visible)
    extra_nested = _diff(catalog_nested, owner_nested)
    missing_nested = _diff(owner_nested, catalog_nested)
    assert extra_visible == () and missing_visible == (), (
        f"{path} visible-node mismatch extra={extra_visible} missing={missing_visible}"
    )
    assert extra_nested == () and missing_nested == (), (
        f"{path} nested-shell mismatch extra={extra_nested} missing={missing_nested}"
    )
    assert owner_group == catalog_group, (
        f"{path} grouping mismatch owner={owner_group} catalog={catalog_group}"
    )


def _assert_required_fixture_identities(
    owner_sig: tuple[tuple[str, ...], tuple[str, ...], object],
) -> None:
    visible, nested, _grouping = owner_sig
    assert "dismissed-old" not in visible
    assert "dismissed-old" not in nested
    assert "recycled" not in visible
    assert "recycled" not in nested
    assert "fresh-launch" in visible
    assert "lane" in visible
    assert "lane--plan" in nested
    assert "lane--gate-pending" in nested
    assert visible.count("lane") == 1
    # A completed plan-chain family has no root record: its shells nest under
    # the family on both sides and no standalone row is invented for it.
    assert {"chain--plan", "chain--mon", "chain--1"} <= set(nested)
    assert "chain" not in visible


def _diff(left: Iterable[str], right: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(left) - set(right)))
