"""Named pure rules that derive Artifacts pane capability verdicts."""

from __future__ import annotations

from collections.abc import Callable

from ._artifact_tab_model import (
    CapabilityVerdict,
    PaneCapability,
    PaneDeclaredFacts,
)

_RULE_DEGRADED = "degraded_safe_host"
_RULE_SUPPRESSED = "provider_suppressed"


def derive_capability_verdicts(
    facts: PaneDeclaredFacts,
) -> tuple[CapabilityVerdict, ...]:
    """Run every named rule for every closed capability."""

    earned = tuple(_rule_for(capability)(facts) for capability in PaneCapability)
    if not facts.suppressions:
        return earned
    applied: list[CapabilityVerdict] = []
    for verdict in earned:
        reason = facts.suppressions.get(verdict.capability.value)
        if reason and verdict.enabled:
            applied.append(
                CapabilityVerdict(
                    capability=verdict.capability,
                    enabled=False,
                    rule=_RULE_SUPPRESSED,
                    fact=verdict.fact,
                    reason=verdict.reason,
                    suppression=reason,
                )
            )
        else:
            applied.append(verdict)
    return tuple(applied)


def _rule_for(
    capability: PaneCapability,
) -> Callable[[PaneDeclaredFacts], CapabilityVerdict]:
    return _RULES[capability]


def _verdict(
    capability: PaneCapability,
    *,
    enabled: bool,
    rule: str,
    fact: str,
    reason: str,
) -> CapabilityVerdict:
    return CapabilityVerdict(
        capability=capability,
        enabled=enabled,
        rule=rule,
        fact=fact,
        reason=reason,
    )


def _rule_entry_navigation(facts: PaneDeclaredFacts) -> CapabilityVerdict:
    if facts.is_degraded:
        return _verdict(
            PaneCapability.ENTRY_NAVIGATION,
            enabled=False,
            rule=_RULE_DEGRADED,
            fact="is_degraded",
            reason="degraded panes expose only safe host behavior",
        )
    if facts.has_inventory or facts.source == "builtin":
        return _verdict(
            PaneCapability.ENTRY_NAVIGATION,
            enabled=True,
            rule="entry_navigation_from_inventory",
            fact="has_inventory" if facts.has_inventory else "builtin_adapter",
            reason="inventory or a built-in list adapter earns entry navigation",
        )
    return _verdict(
        PaneCapability.ENTRY_NAVIGATION,
        enabled=False,
        rule="entry_navigation_from_inventory",
        fact="has_inventory",
        reason="no inventory is declared",
    )


def _rule_entry_open(facts: PaneDeclaredFacts) -> CapabilityVerdict:
    if facts.is_degraded:
        return _verdict(
            PaneCapability.ENTRY_OPEN,
            enabled=False,
            rule=_RULE_DEGRADED,
            fact="is_degraded",
            reason="degraded panes expose only safe host behavior",
        )
    if facts.has_inventory or facts.source == "builtin":
        return _verdict(
            PaneCapability.ENTRY_OPEN,
            enabled=True,
            rule="entry_open_from_inventory",
            fact="has_inventory" if facts.has_inventory else "builtin_adapter",
            reason="inventory or a built-in list adapter earns entry open",
        )
    return _verdict(
        PaneCapability.ENTRY_OPEN,
        enabled=False,
        rule="entry_open_from_inventory",
        fact="has_inventory",
        reason="no inventory is declared",
    )


def _rule_filter_session(facts: PaneDeclaredFacts) -> CapabilityVerdict:
    if facts.is_degraded:
        return _verdict(
            PaneCapability.FILTER_SESSION,
            enabled=False,
            rule=_RULE_DEGRADED,
            fact="is_degraded",
            reason="degraded panes expose only safe host behavior",
        )
    if facts.has_inventory and facts.has_fields:
        return _verdict(
            PaneCapability.FILTER_SESSION,
            enabled=True,
            rule="filter_session_from_inventory_and_fields",
            fact="has_inventory+has_fields",
            reason="inventory plus fields earns a filter/query session",
        )
    return _verdict(
        PaneCapability.FILTER_SESSION,
        enabled=False,
        rule="filter_session_from_inventory_and_fields",
        fact="has_inventory+has_fields",
        reason="filter/query session requires inventory and fields",
    )


def _rule_refresh(facts: PaneDeclaredFacts) -> CapabilityVerdict:
    return _verdict(
        PaneCapability.REFRESH,
        enabled=True,
        rule="refresh_from_host",
        fact="host",
        reason="refresh is safe host behavior on every Artifacts pane",
    )


def _rule_project_scope(facts: PaneDeclaredFacts) -> CapabilityVerdict:
    if facts.is_degraded:
        return _verdict(
            PaneCapability.PROJECT_SCOPE,
            enabled=False,
            rule=_RULE_DEGRADED,
            fact="is_degraded",
            reason="degraded panes expose only safe host behavior",
        )
    if facts.project_scoped:
        return _verdict(
            PaneCapability.PROJECT_SCOPE,
            enabled=True,
            rule="project_scope_from_declaration",
            fact="project_scoped",
            reason="the adapter declares project scoping",
        )
    return _verdict(
        PaneCapability.PROJECT_SCOPE,
        enabled=False,
        rule="project_scope_from_declaration",
        fact="project_scoped",
        reason="the adapter does not participate in project scope",
    )


def _rule_stable_marks(facts: PaneDeclaredFacts) -> CapabilityVerdict:
    if facts.is_degraded:
        return _verdict(
            PaneCapability.STABLE_MARKS,
            enabled=False,
            rule=_RULE_DEGRADED,
            fact="is_degraded",
            reason="degraded panes expose only safe host behavior",
        )
    if facts.has_inventory or facts.source == "builtin":
        return _verdict(
            PaneCapability.STABLE_MARKS,
            enabled=True,
            rule="stable_marks_from_inventory",
            fact="has_inventory" if facts.has_inventory else "builtin_adapter",
            reason="a navigable inventory earns stable marks",
        )
    return _verdict(
        PaneCapability.STABLE_MARKS,
        enabled=False,
        rule="stable_marks_from_inventory",
        fact="has_inventory",
        reason="stable marks require a navigable inventory",
    )


def _rule_detail_scroll(facts: PaneDeclaredFacts) -> CapabilityVerdict:
    if facts.is_degraded:
        return _verdict(
            PaneCapability.DETAIL_SCROLL,
            enabled=False,
            rule=_RULE_DEGRADED,
            fact="is_degraded",
            reason="degraded panes expose only safe host behavior",
        )
    if facts.has_detail:
        return _verdict(
            PaneCapability.DETAIL_SCROLL,
            enabled=True,
            rule="detail_scroll_from_detail",
            fact="has_detail",
            reason="a detail surface earns detail scrolling",
        )
    return _verdict(
        PaneCapability.DETAIL_SCROLL,
        enabled=False,
        rule="detail_scroll_from_detail",
        fact="has_detail",
        reason="no detail surface is declared",
    )


def _rule_stable_reference_copy(facts: PaneDeclaredFacts) -> CapabilityVerdict:
    if facts.is_degraded:
        return _verdict(
            PaneCapability.STABLE_REFERENCE_COPY,
            enabled=False,
            rule=_RULE_DEGRADED,
            fact="is_degraded",
            reason="degraded panes expose only safe host behavior",
        )
    if facts.has_stable_identity:
        return _verdict(
            PaneCapability.STABLE_REFERENCE_COPY,
            enabled=True,
            rule="stable_reference_copy_from_identity",
            fact="has_stable_identity",
            reason="stable reference facts earn copy-reference",
        )
    return _verdict(
        PaneCapability.STABLE_REFERENCE_COPY,
        enabled=False,
        rule="stable_reference_copy_from_identity",
        fact="has_stable_identity",
        reason="no stable reference identity is declared",
    )


def _rule_query_history(facts: PaneDeclaredFacts) -> CapabilityVerdict:
    if facts.is_degraded:
        return _verdict(
            PaneCapability.QUERY_HISTORY,
            enabled=False,
            rule=_RULE_DEGRADED,
            fact="is_degraded",
            reason="degraded panes expose only safe host behavior",
        )
    if facts.has_inventory and facts.has_fields:
        return _verdict(
            PaneCapability.QUERY_HISTORY,
            enabled=True,
            rule="query_history_from_inventory_and_fields",
            fact="has_inventory+has_fields",
            reason="inventory plus fields earns query history",
        )
    return _verdict(
        PaneCapability.QUERY_HISTORY,
        enabled=False,
        rule="query_history_from_inventory_and_fields",
        fact="has_inventory+has_fields",
        reason="query history requires inventory and fields",
    )


def _rule_saved_queries(facts: PaneDeclaredFacts) -> CapabilityVerdict:
    if facts.is_degraded:
        return _verdict(
            PaneCapability.SAVED_QUERIES,
            enabled=False,
            rule=_RULE_DEGRADED,
            fact="is_degraded",
            reason="degraded panes expose only safe host behavior",
        )
    if facts.has_inventory and facts.has_fields:
        return _verdict(
            PaneCapability.SAVED_QUERIES,
            enabled=True,
            rule="saved_queries_from_inventory_and_fields",
            fact="has_inventory+has_fields",
            reason="inventory plus fields earns saved-view behavior",
        )
    return _verdict(
        PaneCapability.SAVED_QUERIES,
        enabled=False,
        rule="saved_queries_from_inventory_and_fields",
        fact="has_inventory+has_fields",
        reason="saved views require inventory and fields",
    )


def _rule_versions(facts: PaneDeclaredFacts) -> CapabilityVerdict:
    if facts.is_degraded:
        return _verdict(
            PaneCapability.VERSIONS,
            enabled=False,
            rule=_RULE_DEGRADED,
            fact="is_degraded",
            reason="degraded panes expose only safe host behavior",
        )
    if facts.has_revisions:
        return _verdict(
            PaneCapability.VERSIONS,
            enabled=True,
            rule="versions_from_revisions",
            fact="has_revisions",
            reason="revision facts earn version operations",
        )
    return _verdict(
        PaneCapability.VERSIONS,
        enabled=False,
        rule="versions_from_revisions",
        fact="has_revisions",
        reason="no revision facts are declared",
    )


def _rule_mutation(facts: PaneDeclaredFacts) -> CapabilityVerdict:
    if facts.is_degraded:
        return _verdict(
            PaneCapability.MUTATION,
            enabled=False,
            rule=_RULE_DEGRADED,
            fact="is_degraded",
            reason="degraded panes expose only safe host behavior",
        )
    if facts.can_mutate and facts.source == "builtin":
        return _verdict(
            PaneCapability.MUTATION,
            enabled=True,
            rule="mutation_from_builtin_adapter",
            fact="can_mutate",
            reason="mutation is available only to built-in adapters",
        )
    return _verdict(
        PaneCapability.MUTATION,
        enabled=False,
        rule="mutation_from_builtin_adapter",
        fact="can_mutate",
        reason="mutation is available only to built-in adapters",
    )


def _rule_plan_approve(facts: PaneDeclaredFacts) -> CapabilityVerdict:
    if facts.is_degraded:
        return _verdict(
            PaneCapability.PLAN_APPROVE,
            enabled=False,
            rule=_RULE_DEGRADED,
            fact="is_degraded",
            reason="degraded panes expose only safe host behavior",
        )
    if facts.is_plan_adapter:
        return _verdict(
            PaneCapability.PLAN_APPROVE,
            enabled=True,
            rule="plan_approve_from_plan_adapter",
            fact="is_plan_adapter",
            reason="plan approval is a built-in Plan-only capability",
        )
    return _verdict(
        PaneCapability.PLAN_APPROVE,
        enabled=False,
        rule="plan_approve_from_plan_adapter",
        fact="is_plan_adapter",
        reason="plan approval is a built-in Plan-only capability",
    )


def _rule_plan_reject(facts: PaneDeclaredFacts) -> CapabilityVerdict:
    if facts.is_degraded:
        return _verdict(
            PaneCapability.PLAN_REJECT,
            enabled=False,
            rule=_RULE_DEGRADED,
            fact="is_degraded",
            reason="degraded panes expose only safe host behavior",
        )
    if facts.is_plan_adapter:
        return _verdict(
            PaneCapability.PLAN_REJECT,
            enabled=True,
            rule="plan_reject_from_plan_adapter",
            fact="is_plan_adapter",
            reason="plan rejection is a built-in Plan-only capability",
        )
    return _verdict(
        PaneCapability.PLAN_REJECT,
        enabled=False,
        rule="plan_reject_from_plan_adapter",
        fact="is_plan_adapter",
        reason="plan rejection is a built-in Plan-only capability",
    )


def _rule_plan_open_bead(facts: PaneDeclaredFacts) -> CapabilityVerdict:
    if facts.is_degraded:
        return _verdict(
            PaneCapability.PLAN_OPEN_BEAD,
            enabled=False,
            rule=_RULE_DEGRADED,
            fact="is_degraded",
            reason="degraded panes expose only safe host behavior",
        )
    if facts.is_plan_adapter:
        return _verdict(
            PaneCapability.PLAN_OPEN_BEAD,
            enabled=True,
            rule="plan_open_bead_from_plan_adapter",
            fact="is_plan_adapter",
            reason="bead-link operations are a built-in Plan-only capability",
        )
    return _verdict(
        PaneCapability.PLAN_OPEN_BEAD,
        enabled=False,
        rule="plan_open_bead_from_plan_adapter",
        fact="is_plan_adapter",
        reason="bead-link operations are a built-in Plan-only capability",
    )


def _rule_status_counters(facts: PaneDeclaredFacts) -> CapabilityVerdict:
    if facts.is_degraded:
        return _verdict(
            PaneCapability.STATUS_COUNTERS,
            enabled=False,
            rule=_RULE_DEGRADED,
            fact="is_degraded",
            reason="degraded panes expose only safe host behavior",
        )
    if facts.status_counters:
        return _verdict(
            PaneCapability.STATUS_COUNTERS,
            enabled=True,
            rule="status_counters_from_declaration",
            fact="status_counters",
            reason="at least one status counter is declared",
        )
    return _verdict(
        PaneCapability.STATUS_COUNTERS,
        enabled=False,
        rule="status_counters_from_declaration",
        fact="status_counters",
        reason="no status counters are declared",
    )


def _rule_shell(facts: PaneDeclaredFacts) -> CapabilityVerdict:
    del facts
    return _verdict(
        PaneCapability.SHELL,
        enabled=True,
        rule="shell_from_host",
        fact="host",
        reason="every Artifacts pane renders through the shared host shell",
    )


def _rule_relations(facts: PaneDeclaredFacts) -> CapabilityVerdict:
    if facts.is_degraded:
        return _verdict(
            PaneCapability.RELATIONS,
            enabled=False,
            rule=_RULE_DEGRADED,
            fact="is_degraded",
            reason="degraded panes expose only safe host behavior",
        )
    if facts.relations:
        return _verdict(
            PaneCapability.RELATIONS,
            enabled=True,
            rule="relations_from_declared_edges",
            fact="relations",
            reason="at least one relation declaration survived validation",
        )
    return _verdict(
        PaneCapability.RELATIONS,
        enabled=False,
        rule="relations_from_declared_edges",
        fact="relations",
        reason="no relation declarations are declared",
    )


def _rule_grouping(facts: PaneDeclaredFacts) -> CapabilityVerdict:
    if facts.is_degraded:
        return _verdict(
            PaneCapability.GROUPING,
            enabled=False,
            rule=_RULE_DEGRADED,
            fact="is_degraded",
            reason="degraded panes expose only safe host behavior",
        )
    if facts.grouping.modes:
        return _verdict(
            PaneCapability.GROUPING,
            enabled=True,
            rule="grouping_from_declared_modes",
            fact="grouping",
            reason="at least one grouping mode is declared",
        )
    return _verdict(
        PaneCapability.GROUPING,
        enabled=False,
        rule="grouping_from_declared_modes",
        fact="grouping",
        reason="no grouping modes are declared",
    )


_RULES = {
    PaneCapability.ENTRY_NAVIGATION: _rule_entry_navigation,
    PaneCapability.ENTRY_OPEN: _rule_entry_open,
    PaneCapability.FILTER_SESSION: _rule_filter_session,
    PaneCapability.REFRESH: _rule_refresh,
    PaneCapability.PROJECT_SCOPE: _rule_project_scope,
    PaneCapability.STABLE_MARKS: _rule_stable_marks,
    PaneCapability.DETAIL_SCROLL: _rule_detail_scroll,
    PaneCapability.STABLE_REFERENCE_COPY: _rule_stable_reference_copy,
    PaneCapability.QUERY_HISTORY: _rule_query_history,
    PaneCapability.SAVED_QUERIES: _rule_saved_queries,
    PaneCapability.VERSIONS: _rule_versions,
    PaneCapability.MUTATION: _rule_mutation,
    PaneCapability.PLAN_APPROVE: _rule_plan_approve,
    PaneCapability.PLAN_REJECT: _rule_plan_reject,
    PaneCapability.PLAN_OPEN_BEAD: _rule_plan_open_bead,
    PaneCapability.RELATIONS: _rule_relations,
    PaneCapability.GROUPING: _rule_grouping,
    PaneCapability.STATUS_COUNTERS: _rule_status_counters,
    PaneCapability.SHELL: _rule_shell,
}
