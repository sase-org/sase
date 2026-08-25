"""Detail-phase coverage: relations, grouping, link targets, and detail load.

Covers the sase-tj.6 phase's own new logic — the parts the pane-phase's
conformance sweep exercises structurally but not semantically: which rows
actually become which relation edges, how grouping buckets family
containers with their members, how ``_known_target_for_ref`` resolves both
the bare and owner-qualified spellings of an ``agent:`` ref, and how the
lazy detail loader degrades for a row with no live artifacts directory.
"""

from __future__ import annotations

from typing import Any

from sase.ace.tui._artifact_tab_contract import compile_builtin_contract
from sase.ace.tui._artifact_tab_model import PaneGroupingModeDecl
from sase.ace.tui.models.group_fold import GroupFoldRegistry
from sase.ace.tui.relations.agents import build_agents_relation_index
from sase.ace.tui.relations.artifact_links import _known_target_for_ref
from sase.ace.tui.widgets.artifacts.agents_data import AgentsSnapshot
from sase.ace.tui.widgets.artifacts.agents_detail import (
    build_agent_detail,
    load_agent_detail,
)
from sase.ace.tui.widgets.artifacts.agents_list import build_grouped_agent_rows
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.agents.catalog import AgentCatalogRow
from tests._agent_catalog_helpers import make_agent_catalog_row


def _agent_row(name: str, **overrides: Any) -> AgentCatalogRow:
    defaults: dict[str, Any] = {
        "kind": ("member",),
        "project": "alpha",
        "state": "active",
        "status": "RUNNING",
        "from_artifact_index": True,
    }
    defaults.update(overrides)
    return make_agent_catalog_row(name, **defaults)


def _contract() -> Any:
    return compile_builtin_contract("agents", label="Agent", icon="⬡", accent="#0062FF")


def _snapshot(*rows: AgentCatalogRow) -> AgentsSnapshot:
    return AgentsSnapshot(
        project="alpha",
        rows=rows,
        total_row_count=len(rows),
        truncated=False,
    )


def test_family_relation_links_member_to_container_not_itself() -> None:
    container = _agent_row("0b4", kind=("family",), family=None)
    member = _agent_row("0b4--0", kind=("member",), family="0b4", role="code")
    index = build_agents_relation_index(
        _snapshot(container, member), contract=_contract()
    )

    member_target = ArtifactEntryTarget("agents", ("0b4--0",))
    container_target = ArtifactEntryTarget("agents", ("0b4",))
    edges = index.edges_for_relation(member_target, "family")
    assert any(edge.target == container_target for edge in edges)
    # The container itself has no self-referential family edge.
    assert not index.edges_for_relation(container_target, "family")


def test_clan_relation_links_member_to_clan_container() -> None:
    container = _agent_row("research.12", kind=("clan",), clan="research.12")
    member = _agent_row("research.12--0", kind=("member",), clan="research.12")
    index = build_agents_relation_index(
        _snapshot(container, member), contract=_contract()
    )

    edges = index.edges_for_relation(
        ArtifactEntryTarget("agents", ("research.12--0",)), "clan"
    )
    assert any(
        edge.target == ArtifactEntryTarget("agents", ("research.12",)) for edge in edges
    )


def test_parent_relation_resolves_through_raw_suffix() -> None:
    parent = _agent_row("parent-agent", raw_suffix="20260101000000")
    child = _agent_row("child-agent", parent_timestamp="20260101000000")
    index = build_agents_relation_index(_snapshot(parent, child), contract=_contract())

    edges = index.edges_for_relation(
        ArtifactEntryTarget("agents", ("child-agent",)), "parent"
    )
    assert any(
        edge.target == ArtifactEntryTarget("agents", ("parent-agent",))
        for edge in edges
    )


def test_retry_chain_groups_root_and_every_attempt_together() -> None:
    root = _agent_row(
        "attempt-0", raw_suffix="20260101000000", retried_as_timestamp="20260101000100"
    )
    retry_1 = _agent_row(
        "attempt-1",
        raw_suffix="20260101000100",
        retry_attempt=1,
        retry_of_timestamp="20260101000000",
        retry_chain_root_timestamp="20260101000000",
        retried_as_timestamp="20260101000200",
    )
    retry_2 = _agent_row(
        "attempt-2",
        raw_suffix="20260101000200",
        retry_attempt=2,
        retry_of_timestamp="20260101000100",
        retry_chain_root_timestamp="20260101000000",
    )
    index = build_agents_relation_index(
        _snapshot(root, retry_1, retry_2), contract=_contract()
    )

    root_targets = {
        edge.target
        for edge in index.edges_for_relation(
            ArtifactEntryTarget("agents", ("attempt-0",)), "retry_chain"
        )
    }
    assert root_targets == {
        ArtifactEntryTarget("agents", ("attempt-1",)),
        ArtifactEntryTarget("agents", ("attempt-2",)),
    }


def test_known_target_for_ref_matches_bare_local_name() -> None:
    known = frozenset({ArtifactEntryTarget("agents", ("0b4--0",))})
    assert _known_target_for_ref("agent", "0b4--0", known) == ArtifactEntryTarget(
        "agents", ("0b4--0",)
    )


def test_known_target_for_ref_returns_none_for_unknown_agent() -> None:
    known = frozenset({ArtifactEntryTarget("agents", ("0b4--0",))})
    assert _known_target_for_ref("agent", "not-a-row", known) is None


def test_by_family_grouping_clusters_container_with_its_members() -> None:
    container = _agent_row("0b4", kind=("family",), family=None)
    member_a = _agent_row("0b4--0", family="0b4")
    member_b = _agent_row("0b4--1", family="0b4")
    standalone = _agent_row("solo-agent", family=None)
    snapshot = _snapshot(container, member_a, member_b, standalone)
    mode = PaneGroupingModeDecl(id="by_family", label="Family", keys=("family",))

    result = build_grouped_agent_rows(
        snapshot, mode=mode, fold_registry=GroupFoldRegistry()
    )

    banners = {row.banner.group_key: row.banner for row in result.rows if row.banner}
    family_banner = banners[("0b4",)]
    assert family_banner.member_count == 3  # container + both members
    assert ArtifactEntryTarget("agents", ("0b4",)) in family_banner.member_targets
    assert ArtifactEntryTarget("agents", ("0b4--0",)) in family_banner.member_targets
    assert ArtifactEntryTarget("agents", ("0b4--1",)) in family_banner.member_targets
    assert (
        ArtifactEntryTarget("agents", ("solo-agent",))
        not in family_banner.member_targets
    )


def test_load_agent_detail_degrades_for_a_row_with_no_artifacts_dir() -> None:
    row = _agent_row("thin-row", artifacts_dir=None, bundle_path=None)
    detail = load_agent_detail(row)
    assert detail.artifacts_dir_live is False
    assert detail.prompt_preview is None
    assert detail.chat_path is None

    text = build_agent_detail(row, detail)
    assert "thin-row" in text.plain
    assert "No prompt available" in text.plain
    assert "No chat file recorded" in text.plain


def test_build_agent_detail_handles_no_selection() -> None:
    assert "Select an agent" in build_agent_detail(None, None).plain
