"""Unit coverage for artifact contract capability derivation rules."""

from __future__ import annotations

import pytest

from sase.ace.tui._artifact_tab_model import (
    PaneCapability,
    PaneGroupingDecl,
    PaneGroupingModeDecl,
    PaneRelationDecl,
    RelationKind,
)
from sase.ace.tui._artifact_tab_contract_rules import derive_capability_verdicts

from .contract_compiler_support import enabled, facts, verdict


def test_every_closed_capability_has_a_named_verdict() -> None:
    verdicts = derive_capability_verdicts(facts())
    assert [item.capability for item in verdicts] == list(PaneCapability)
    assert all(item.rule for item in verdicts)


@pytest.mark.parametrize(
    ("capability", "rule"),
    [
        (PaneCapability.ENTRY_NAVIGATION, "entry_navigation_from_inventory"),
        (PaneCapability.ENTRY_OPEN, "entry_open_from_inventory"),
        (PaneCapability.FILTER_SESSION, "filter_session_from_inventory_and_fields"),
        (PaneCapability.REFRESH, "refresh_from_host"),
        (PaneCapability.PROJECT_SCOPE, "project_scope_from_declaration"),
        (PaneCapability.STABLE_MARKS, "stable_marks_from_inventory"),
        (PaneCapability.DETAIL_SCROLL, "detail_scroll_from_detail"),
        (PaneCapability.STABLE_REFERENCE_COPY, "stable_reference_copy_from_identity"),
        (PaneCapability.QUERY_HISTORY, "query_history_from_inventory_and_fields"),
        (PaneCapability.SAVED_QUERIES, "saved_queries_from_inventory_and_fields"),
        (PaneCapability.VERSIONS, "versions_from_revisions"),
        (PaneCapability.MUTATION, "mutation_from_builtin_adapter"),
        (PaneCapability.PLAN_APPROVE, "plan_approve_from_plan_adapter"),
        (PaneCapability.PLAN_REJECT, "plan_reject_from_plan_adapter"),
        (PaneCapability.RELATIONS, "relations_from_declared_edges"),
        (PaneCapability.GROUPING, "grouping_from_declared_modes"),
        (PaneCapability.STATUS_COUNTERS, "status_counters_from_declaration"),
        (PaneCapability.SHELL, "shell_from_host"),
    ],
)
def test_named_derivation_rules(capability: PaneCapability, rule: str) -> None:
    assert verdict(facts(), capability).rule == rule


def test_inventory_and_fields_earn_filter_history_and_saved_views() -> None:
    earned = enabled(facts(has_inventory=True, has_fields=True))
    assert PaneCapability.FILTER_SESSION in earned
    assert PaneCapability.QUERY_HISTORY in earned
    assert PaneCapability.SAVED_QUERIES in earned

    missing = enabled(facts(has_inventory=True, has_fields=False))
    assert PaneCapability.FILTER_SESSION not in missing
    assert PaneCapability.QUERY_HISTORY not in missing
    assert PaneCapability.SAVED_QUERIES not in missing


def test_stable_identity_earns_copy_and_revisions_earn_versions() -> None:
    assert PaneCapability.STABLE_REFERENCE_COPY in enabled(
        facts(has_stable_identity=True)
    )
    assert PaneCapability.STABLE_REFERENCE_COPY not in enabled(
        facts(has_stable_identity=False)
    )
    assert PaneCapability.VERSIONS in enabled(facts(has_revisions=True))
    assert PaneCapability.VERSIONS not in enabled(facts(has_revisions=False))


def test_mutation_is_builtin_only_and_plan_ops_are_plan_only() -> None:
    builtin = enabled(facts(source="builtin", can_mutate=True, is_plan_adapter=False))
    provider = enabled(facts(source="provider", can_mutate=True, is_plan_adapter=False))
    plan = enabled(facts(is_plan_adapter=True))
    assert PaneCapability.MUTATION in builtin
    assert PaneCapability.MUTATION not in provider
    assert PaneCapability.PLAN_APPROVE in plan
    assert PaneCapability.PLAN_REJECT in plan
    assert PaneCapability.PLAN_APPROVE not in provider


def test_undeclared_relation_and_grouping_capabilities_stay_off() -> None:
    earned = enabled(facts())
    assert PaneCapability.RELATIONS not in earned
    assert PaneCapability.GROUPING not in earned
    assert PaneCapability.STATUS_COUNTERS not in earned
    assert PaneCapability.SHELL in earned


def test_declared_relations_and_grouping_earn_capabilities() -> None:
    declared_facts = facts(
        relations=(
            PaneRelationDecl(
                name="parents",
                kind=RelationKind.HIERARCHY,
                label="Parents",
                source="parent",
                target_pane=None,
                inverse="children",
                directed=True,
                transitive=True,
            ),
        ),
        grouping=PaneGroupingDecl(
            modes=(
                PaneGroupingModeDecl(
                    id="by_status",
                    label="Status",
                    keys=("status",),
                ),
            ),
            default_mode="by_status",
        ),
    )
    earned = enabled(declared_facts)
    assert PaneCapability.RELATIONS in earned
    assert PaneCapability.GROUPING in earned


def test_valid_suppression_turns_earned_capability_off() -> None:
    declared_facts = facts(
        suppressions={"filter_session": "notes are browsed, not queried"}
    )
    capability_verdict = verdict(declared_facts, PaneCapability.FILTER_SESSION)
    assert capability_verdict.enabled is False
    assert capability_verdict.rule == "provider_suppressed"
    assert capability_verdict.suppression == "notes are browsed, not queried"


def test_degraded_facts_keep_only_refresh_and_shell() -> None:
    earned = enabled(facts(is_degraded=True, is_plan_adapter=True, can_mutate=True))
    assert earned == {PaneCapability.REFRESH, PaneCapability.SHELL}
