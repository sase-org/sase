"""Unit coverage for ArtifactsPaneContract compilation and derivation rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui._artifact_tab_contract import (
    GENERIC_DOCUMENT_COPY_TARGETS,
    PLAN_COPY_TARGETS,
    _extract_provider_suppressions,
    _presentation_digest,
    _provider_facts_from_spec,
    compile_builtin_contract,
    compile_provider_contract,
    contract_with_digit,
)
from sase.ace.tui._artifact_tab_contract_rules import derive_capability_verdicts
from sase.ace.tui._artifact_tab_descriptors import (
    assign_artifacts_digit_shortcuts,
    fixed_descriptor,
    provider_descriptors,
)
from sase.ace.tui._artifact_tab_model import (
    PaneCapability,
    PaneDeclaredFacts,
    ProjectProviderRecord,
    ProviderDiscoveryIssue,
)
from sase.ace.tui.artifact_tabs import (
    artifacts_pane_contract,
    configured_artifacts_pane_ids,
    descriptor_for_artifacts_pane_id,
    descriptor_for_artifacts_subtab,
    reset_artifacts_subtabs_cache,
)
from sase.artifact_providers import builtin_plan_ref_provider_spec
from sase.sidecar_ref_config import SidecarRefPolicy


def _facts(**overrides: object) -> PaneDeclaredFacts:
    values: dict[str, object] = {
        "source": "provider",
        "adapter": None,
        "is_degraded": False,
        "has_inventory": True,
        "has_fields": True,
        "has_stable_identity": True,
        "has_revisions": False,
        "can_mutate": False,
        "is_plan_adapter": False,
        "project_scoped": True,
        "has_detail": True,
        "suppressions": {},
    }
    values.update(overrides)
    return PaneDeclaredFacts(**values)  # type: ignore[arg-type]


def _enabled(facts: PaneDeclaredFacts) -> set[PaneCapability]:
    return {
        verdict.capability
        for verdict in derive_capability_verdicts(facts)
        if verdict.enabled
    }


def _verdict(facts: PaneDeclaredFacts, capability: PaneCapability):
    return next(
        item
        for item in derive_capability_verdicts(facts)
        if item.capability == capability
    )


def _document_spec(
    *,
    kind: str = "notes",
    properties: dict[str, object] | None = None,
    identity: dict[str, object] | None = None,
    inventory: dict[str, object] | None = None,
    capabilities: dict[str, object] | None = None,
) -> dict[str, object]:
    ref: dict[str, object] = {
        "kind": kind,
        "icon": "¶",
        "expansion_format": "@{checkout_path}",
        "properties": properties
        if properties is not None
        else {
            "title": {"type": "string", "source": "markdown_frontmatter"},
            "status": {"type": "string", "source": "markdown_frontmatter"},
        },
        "detail": {"fields": ["title", "status"]},
        "identity": {} if identity is None else identity,
        "inventory": {"globs": ["**/*.md"]} if inventory is None else inventory,
        "publication": {
            "link": "vcs_permalink",
            "referenced_by": "markdown_table",
        },
    }
    if capabilities is not None:
        ref["capabilities"] = capabilities
    return {
        "schema_version": 1,
        "provider": kind,
        "ref": ref,
    }


def test_every_closed_capability_has_a_named_verdict() -> None:
    verdicts = derive_capability_verdicts(_facts())
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
        (PaneCapability.PLAN_OPEN_BEAD, "plan_open_bead_from_plan_adapter"),
        (PaneCapability.RELATIONS, "later_phase_reserved"),
        (PaneCapability.GROUPING, "later_phase_reserved"),
        (PaneCapability.STATUS_COUNTERS, "later_phase_reserved"),
        (PaneCapability.SHELL, "later_phase_reserved"),
    ],
)
def test_named_derivation_rules(capability: PaneCapability, rule: str) -> None:
    assert _verdict(_facts(), capability).rule == rule


def test_inventory_and_fields_earn_filter_history_and_saved_views() -> None:
    earned = _enabled(_facts(has_inventory=True, has_fields=True))
    assert PaneCapability.FILTER_SESSION in earned
    assert PaneCapability.QUERY_HISTORY in earned
    assert PaneCapability.SAVED_QUERIES in earned

    missing = _enabled(_facts(has_inventory=True, has_fields=False))
    assert PaneCapability.FILTER_SESSION not in missing
    assert PaneCapability.QUERY_HISTORY not in missing
    assert PaneCapability.SAVED_QUERIES not in missing


def test_stable_identity_earns_copy_and_revisions_earn_versions() -> None:
    assert PaneCapability.STABLE_REFERENCE_COPY in _enabled(
        _facts(has_stable_identity=True)
    )
    assert PaneCapability.STABLE_REFERENCE_COPY not in _enabled(
        _facts(has_stable_identity=False)
    )
    assert PaneCapability.VERSIONS in _enabled(_facts(has_revisions=True))
    assert PaneCapability.VERSIONS not in _enabled(_facts(has_revisions=False))


def test_mutation_is_builtin_only_and_plan_ops_are_plan_only() -> None:
    builtin = _enabled(_facts(source="builtin", can_mutate=True, is_plan_adapter=False))
    provider = _enabled(
        _facts(source="provider", can_mutate=True, is_plan_adapter=False)
    )
    plan = _enabled(_facts(is_plan_adapter=True))
    assert PaneCapability.MUTATION in builtin
    assert PaneCapability.MUTATION not in provider
    assert PaneCapability.PLAN_APPROVE in plan
    assert PaneCapability.PLAN_REJECT in plan
    assert PaneCapability.PLAN_OPEN_BEAD in plan
    assert PaneCapability.PLAN_APPROVE not in provider


def test_later_phase_capabilities_stay_off() -> None:
    earned = _enabled(_facts())
    assert PaneCapability.RELATIONS not in earned
    assert PaneCapability.GROUPING not in earned
    assert PaneCapability.STATUS_COUNTERS not in earned
    assert PaneCapability.SHELL not in earned


def test_valid_suppression_turns_earned_capability_off() -> None:
    facts = _facts(suppressions={"filter_session": "notes are browsed, not queried"})
    verdict = _verdict(facts, PaneCapability.FILTER_SESSION)
    assert verdict.enabled is False
    assert verdict.rule == "provider_suppressed"
    assert verdict.suppression == "notes are browsed, not queried"


def test_degraded_facts_keep_only_refresh() -> None:
    earned = _enabled(_facts(is_degraded=True, is_plan_adapter=True, can_mutate=True))
    assert earned == {PaneCapability.REFRESH}


@pytest.mark.parametrize("adapter", ["stitches", "patches", "beads", "files"])
def test_builtin_contract_snapshots(adapter: str) -> None:
    labels = {
        "stitches": "Stitch",
        "patches": "Patch",
        "beads": "Bead",
        "files": "File",
    }
    contract = compile_builtin_contract(
        adapter,
        label=labels[adapter],
        icon="x",
        accent="#000000",
    )
    assert contract.id == adapter
    assert contract.adapter == adapter
    assert contract.has(PaneCapability.ENTRY_NAVIGATION)
    assert contract.has(PaneCapability.REFRESH)
    assert contract.has(PaneCapability.STABLE_REFERENCE_COPY)
    assert contract.has(PaneCapability.FILTER_SESSION)
    assert not contract.has(PaneCapability.RELATIONS)
    assert contract.presentation_digest
    assert len(contract.verdicts) == len(PaneCapability)
    if adapter == "files":
        assert contract.has(PaneCapability.VERSIONS)
        assert not contract.has(PaneCapability.MUTATION)
    elif adapter in {"patches", "beads"}:
        assert contract.has(PaneCapability.MUTATION)
        assert not contract.has(PaneCapability.VERSIONS)
    else:
        assert not contract.has(PaneCapability.MUTATION)
        assert not contract.has(PaneCapability.VERSIONS)
    if adapter == "patches":
        assert not contract.has(PaneCapability.PROJECT_SCOPE)
    else:
        assert contract.has(PaneCapability.PROJECT_SCOPE)


def test_provider_fact_extraction_from_schema_v1() -> None:
    spec = _document_spec()
    facts = _provider_facts_from_spec("notes", spec, is_degraded=False, suppressions={})
    assert facts.has_inventory is True
    assert facts.has_fields is True
    assert facts.has_stable_identity is True
    assert facts.has_revisions is False
    assert facts.can_mutate is False
    assert facts.is_plan_adapter is False

    empty = _provider_facts_from_spec(
        "notes",
        _document_spec(properties={}, inventory={"globs": []}),
        is_degraded=False,
        suppressions={},
    )
    assert empty.has_inventory is False
    assert empty.has_fields is False


def test_revision_property_earns_versions_fact() -> None:
    facts = _provider_facts_from_spec(
        "notes",
        _document_spec(
            properties={
                "revision": {"type": "string", "source": "markdown_frontmatter"}
            }
        ),
        is_degraded=False,
        suppressions={},
    )
    assert facts.has_revisions is True


def test_plan_provider_earns_plan_only_capabilities() -> None:
    result = compile_provider_contract(
        kind="plan",
        label="Plan",
        icon="✎",
        accent="#AF87FF",
        spec=builtin_plan_ref_provider_spec(),
        provider_spec_digest="abc",
    )
    contract = result.contract
    assert result.error is None
    assert contract.has(PaneCapability.PLAN_APPROVE)
    assert contract.has(PaneCapability.FILTER_SESSION)
    assert contract.copy_targets == PLAN_COPY_TARGETS
    assert contract.copy_group == "artifacts_plans"
    assert not contract.has(PaneCapability.MUTATION)
    assert not contract.has(PaneCapability.VERSIONS)


def test_unknown_document_provider_gets_generic_copy_targets() -> None:
    result = compile_provider_contract(
        kind="notes",
        label="Note",
        icon="¶",
        accent="#5FAFFF",
        spec=_document_spec(),
        provider_spec_digest="def",
    )
    contract = result.contract
    assert contract.copy_group == "artifacts_notes"
    assert contract.copy_targets == GENERIC_DOCUMENT_COPY_TARGETS
    assert contract.has(PaneCapability.FILTER_SESSION)
    assert contract.has(PaneCapability.STABLE_REFERENCE_COPY)
    assert not contract.has(PaneCapability.MUTATION)
    assert not contract.has(PaneCapability.VERSIONS)
    assert not contract.has(PaneCapability.PLAN_APPROVE)
    assert not contract.has(PaneCapability.RELATIONS)


def test_valid_suppression_compiles_without_degrading() -> None:
    result = compile_provider_contract(
        kind="notes",
        label="Note",
        icon="¶",
        accent="#5FAFFF",
        spec=_document_spec(
            capabilities={"suppress": {"filter_session": "browse only"}}
        ),
        provider_spec_digest="ghi",
    )
    assert result.error is None
    assert not result.contract.has(PaneCapability.FILTER_SESSION)
    verdict = result.contract.verdict_for(PaneCapability.FILTER_SESSION)
    assert verdict is not None
    assert verdict.suppression == "browse only"


@pytest.mark.parametrize(
    "capabilities",
    [
        {"enable": ["filter_session"]},
        {"suppress": {"not_a_capability": "nope"}},
        {"suppress": {"filter_session": ""}},
        {"suppress": {"filter_session": 1}},
        ["filter_session"],
    ],
)
def test_invalid_suppression_degrades_descriptor(capabilities: object) -> None:
    result = compile_provider_contract(
        kind="notes",
        label="Note",
        icon="¶",
        accent="#5FAFFF",
        spec=_document_spec(capabilities=capabilities),  # type: ignore[arg-type]
        provider_spec_digest="jkl",
    )
    assert result.error
    assert result.error_code == "invalid_ref_capabilities"
    assert result.contract.has(PaneCapability.REFRESH)
    assert not result.contract.has(PaneCapability.FILTER_SESSION)
    assert not result.contract.has(PaneCapability.PLAN_APPROVE)


def test_invalid_suppression_marks_provider_descriptor_degraded() -> None:
    spec = _document_spec(capabilities={"enable": True})
    descriptors = provider_descriptors(
        (
            ProjectProviderRecord(
                project="proj",
                display_name="Proj",
                workspace_dir="/tmp/proj",
                role="notes",
                root=Path("/tmp/proj"),
                policy=SidecarRefPolicy(
                    role="notes",
                    ref_kind="notes",
                    is_document=True,
                    spec=spec,
                ),
            ),
        )
    )
    assert len(descriptors) == 1
    assert descriptors[0].is_degraded
    assert descriptors[0].error_code == "invalid_ref_capabilities"
    assert descriptors[0].contract is not None
    assert descriptors[0].contract.has(PaneCapability.REFRESH)


def test_degraded_descriptor_satisfies_every_conformance_check() -> None:
    """A degraded provider stays named/navigable and renders the shared shell.

    Runs the full conformance harness (including the shell-render check)
    against a genuinely degraded descriptor, not just the healthy built-ins
    and synthetic provider covered elsewhere.
    """
    from .harness import PANE_CONFORMANCE_CHECKS

    spec = _document_spec(capabilities={"enable": True})
    descriptors = provider_descriptors(
        (
            ProjectProviderRecord(
                project="proj",
                display_name="Proj",
                workspace_dir="/tmp/proj",
                role="notes",
                root=Path("/tmp/proj"),
                policy=SidecarRefPolicy(
                    role="notes",
                    ref_kind="notes",
                    is_document=True,
                    spec=spec,
                ),
            ),
        )
    )
    assert descriptors[0].is_degraded
    for _name, check in PANE_CONFORMANCE_CHECKS:
        check(descriptors[0])


def test_digit_assignment_synchronizes_contract() -> None:
    descriptors = assign_artifacts_digit_shortcuts(
        (
            fixed_descriptor("stitches"),
            fixed_descriptor("patches"),
            fixed_descriptor("beads"),
            fixed_descriptor("files"),
        )
    )
    for index, descriptor in enumerate(descriptors):
        assert descriptor.contract is not None
        assert descriptor.digit_shortcut == str(index + 1)
        assert descriptor.contract.digit == descriptor.digit_shortcut
        assert descriptor.contract.order == index
        assert descriptor.contract.label == descriptor.label


def test_presentation_digest_is_deterministic_and_sensitive() -> None:
    first = compile_builtin_contract(
        "beads",
        label="Bead",
        icon="◈",
        accent="#D787FF",
    )
    second = compile_builtin_contract(
        "beads",
        label="Bead",
        icon="◈",
        accent="#D787FF",
    )
    changed = compile_builtin_contract(
        "beads",
        label="Beads",
        icon="◈",
        accent="#D787FF",
    )
    assert first.presentation_digest == second.presentation_digest
    assert first.presentation_digest != changed.presentation_digest
    with_digit = contract_with_digit(first, digit="3", order=2)
    assert with_digit.presentation_digest != first.presentation_digest
    assert _presentation_digest(with_digit) == with_digit.presentation_digest


def test_extract_provider_suppressions_accepts_valid_block() -> None:
    suppressions, error, code = _extract_provider_suppressions(
        _document_spec(capabilities={"suppress": {"versions": "no history"}})
    )
    assert error is None
    assert code is None
    assert suppressions == {"versions": "no history"}


def test_exact_lookup_does_not_normalize_unknown_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_artifacts_subtabs_cache()
    monkeypatch.setattr(
        "sase.ace.tui.artifact_tabs.resolve_artifacts_subtabs",
        lambda: assign_artifacts_digit_shortcuts(
            (
                fixed_descriptor("stitches"),
                fixed_descriptor("patches"),
                fixed_descriptor("beads"),
                fixed_descriptor("files"),
            )
        ),
    )
    assert descriptor_for_artifacts_pane_id("missing") is None
    assert artifacts_pane_contract("missing") is None
    assert descriptor_for_artifacts_subtab("missing") is not None
    assert descriptor_for_artifacts_subtab("missing").id == "stitches"
    assert configured_artifacts_pane_ids() == (
        "stitches",
        "patches",
        "beads",
        "files",
    )


def test_degraded_discovery_keeps_safe_contract() -> None:
    descriptors = provider_descriptors(
        (),
        (
            ProviderDiscoveryIssue(
                message="artifact ref provider 'research-docs' is not installed",
                code="missing_ref_provider",
                kind="research",
            ),
        ),
    )
    descriptor = descriptors[0]
    assert descriptor.is_degraded
    assert descriptor.contract is not None
    assert descriptor.contract.has(PaneCapability.REFRESH)
    assert not descriptor.contract.has(PaneCapability.FILTER_SESSION)
    assert not descriptor.contract.has(PaneCapability.MUTATION)
