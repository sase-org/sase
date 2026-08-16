"""Unit coverage for ArtifactsPaneContract compilation and derivation rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.query_profile import compiled_profile_for_builtin_pane
from sase.ace.tui._artifact_tab_contract import (
    GENERIC_DOCUMENT_COPY_TARGETS,
    PLAN_COPY_TARGETS,
    _presentation_digest,
    compile_builtin_contract,
    compile_provider_contract,
    contract_with_digit,
)
from sase.ace.tui._artifact_tab_contract_provider import (
    extract_provider_grouping,
    extract_provider_relations,
    extract_provider_suppressions,
    provider_facts_from_spec,
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
    PaneGroupingDecl,
    PaneGroupingModeDecl,
    PaneRelationDecl,
    ProjectProviderRecord,
    ProviderDiscoveryIssue,
    RelationKind,
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
    relations: list[object] | None = None,
    grouping: dict[str, object] | None = None,
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
    if relations is not None:
        ref["relations"] = relations
    if grouping is not None:
        ref["grouping"] = grouping
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
        (PaneCapability.RELATIONS, "relations_from_declared_edges"),
        (PaneCapability.GROUPING, "grouping_from_declared_modes"),
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


def test_undeclared_relation_and_grouping_capabilities_stay_off() -> None:
    earned = _enabled(_facts())
    assert PaneCapability.RELATIONS not in earned
    assert PaneCapability.GROUPING not in earned
    assert PaneCapability.STATUS_COUNTERS not in earned
    assert PaneCapability.SHELL not in earned


def test_declared_relations_and_grouping_earn_capabilities() -> None:
    facts = _facts(
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
    earned = _enabled(facts)
    assert PaneCapability.RELATIONS in earned
    assert PaneCapability.GROUPING in earned


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
    assert contract.has(PaneCapability.RELATIONS)
    assert contract.has(PaneCapability.GROUPING)
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
    assert contract.has(PaneCapability.PROJECT_SCOPE)
    assert contract.relations
    assert contract.grouping.modes


def test_patch_contract_names_relation_and_grouping_declarations() -> None:
    contract = compile_builtin_contract(
        "patches",
        label="Patch",
        icon="x",
        accent="#000000",
    )
    assert [item.name for item in contract.relations] == [
        "ancestors",
        "children",
        "siblings",
    ]
    assert [item.kind for item in contract.relations] == [
        RelationKind.HIERARCHY,
        RelationKind.HIERARCHY,
        RelationKind.FAMILY,
    ]
    assert contract.grouping.default_mode == "by_project"
    assert [item.id for item in contract.grouping.modes] == [
        "by_project",
        "by_date",
        "by_status",
    ]


@pytest.mark.parametrize("adapter", ["stitches", "patches", "beads", "files"])
def test_builtin_contract_carries_the_matching_compiled_profile(adapter: str) -> None:
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
    expected = compiled_profile_for_builtin_pane(adapter)
    assert expected is not None
    assert contract.query_profile == expected
    assert contract.query_profile.pane_id == adapter
    payload = contract.explanation_payload()
    assert payload["query_profile"] == expected.to_wire()


def test_provider_contract_derives_query_profile_from_properties() -> None:
    result = compile_provider_contract(
        kind="notes",
        label="Note",
        icon="¶",
        accent="#5FAFFF",
        spec=_document_spec(),
        provider_spec_digest="def",
    )
    profile = result.contract.query_profile
    assert profile.pane_id == "ref:notes"
    assert profile.boolean is False
    assert {item.key for item in profile.fields} == {"title", "status"}


def test_plan_provider_contract_uses_the_plans_query_profile() -> None:
    result = compile_provider_contract(
        kind="plan",
        label="Plan",
        icon="✎",
        accent="#AF87FF",
        spec=builtin_plan_ref_provider_spec(),
        provider_spec_digest="abc",
    )
    expected = compiled_profile_for_builtin_pane("ref:plan")
    assert expected is not None
    assert result.contract.query_profile == expected


def test_invalid_provider_query_profile_degrades_contract_with_empty_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.query_profile import QueryProfileError

    def _raise(_kind: str, _spec: object) -> None:
        raise QueryProfileError("boom")

    monkeypatch.setattr(
        "sase.ace.tui._artifact_tab_contract_provider.provider_query_schema",
        _raise,
    )
    result = compile_provider_contract(
        kind="notes",
        label="Note",
        icon="¶",
        accent="#5FAFFF",
        spec=_document_spec(),
        provider_spec_digest="def",
    )
    assert result.error == "boom"
    assert result.error_code == "invalid_query_profile"
    assert result.contract.query_profile.fields == ()
    assert result.contract.query_profile.pane_id == "ref:notes"
    assert not result.contract.has(PaneCapability.FILTER_SESSION)


def test_provider_fact_extraction_from_schema_v1() -> None:
    spec = _document_spec()
    facts = provider_facts_from_spec("notes", spec, is_degraded=False, suppressions={})
    assert facts.has_inventory is True
    assert facts.has_fields is True
    assert facts.has_stable_identity is True
    assert facts.has_revisions is False
    assert facts.can_mutate is False
    assert facts.is_plan_adapter is False

    empty = provider_facts_from_spec(
        "notes",
        _document_spec(properties={}, inventory={"globs": []}),
        is_degraded=False,
        suppressions={},
    )
    assert empty.has_inventory is False
    assert empty.has_fields is False


def test_revision_property_earns_versions_fact() -> None:
    facts = provider_facts_from_spec(
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
    assert contract.has(PaneCapability.RELATIONS)
    assert contract.has(PaneCapability.GROUPING)
    assert [item.name for item in contract.relations] == [
        "parent",
        "children",
        "beads",
    ]


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
    assert not contract.has(PaneCapability.GROUPING)
    relations = contract.verdict_for(PaneCapability.RELATIONS)
    grouping = contract.verdict_for(PaneCapability.GROUPING)
    assert relations is not None
    assert relations.rule == "relations_from_declared_edges"
    assert grouping is not None
    assert grouping.rule == "grouping_from_declared_modes"


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


def test_provider_relation_and_grouping_declarations_compile() -> None:
    result = compile_provider_contract(
        kind="notes",
        label="Note",
        icon="¶",
        accent="#5FAFFF",
        spec=_document_spec(
            relations=[
                {
                    "name": "parents",
                    "kind": "hierarchy",
                    "label": "Parents",
                    "source": "status",
                    "target_pane": None,
                    "inverse": "children",
                    "directed": True,
                    "transitive": True,
                }
            ],
            grouping={
                "default_mode": "by_status",
                "modes": [{"id": "by_status", "label": "Status", "keys": ["status"]}],
            },
        ),
        provider_spec_digest="rel",
        configured_pane_ids=("ref:notes", "beads"),
    )
    contract = result.contract
    assert result.error is None
    assert contract.has(PaneCapability.RELATIONS)
    assert contract.has(PaneCapability.GROUPING)
    assert contract.relations[0].kind is RelationKind.HIERARCHY
    assert contract.grouping.default_mode == "by_status"


def test_provider_relation_capability_can_be_suppressed() -> None:
    result = compile_provider_contract(
        kind="notes",
        label="Note",
        icon="¶",
        accent="#5FAFFF",
        spec=_document_spec(
            capabilities={"suppress": {"relations": "read only"}},
            relations=[
                {
                    "name": "parents",
                    "kind": "hierarchy",
                    "label": "Parents",
                    "source": "status",
                    "target_pane": None,
                    "inverse": "children",
                    "directed": True,
                    "transitive": True,
                }
            ],
        ),
        provider_spec_digest="rel",
    )
    assert result.error is None
    assert not result.contract.has(PaneCapability.RELATIONS)
    verdict = result.contract.verdict_for(PaneCapability.RELATIONS)
    assert verdict is not None
    assert verdict.rule == "provider_suppressed"
    assert verdict.suppression == "read only"


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


@pytest.mark.parametrize(
    ("relations", "message"),
    [
        (
            [{"name": "parents", "kind": "hierarchy", "label": "Parents"}],
            "source",
        ),
        (
            [
                {
                    "name": "parents",
                    "kind": "hierarchy",
                    "label": "Parents",
                    "source": "missing",
                    "directed": True,
                    "transitive": True,
                }
            ],
            "declared ref.properties",
        ),
        (
            [
                {
                    "name": "parents",
                    "kind": "hierarchy",
                    "label": "Parents",
                    "source": "status",
                    "target_pane": "ref:unknown",
                    "directed": True,
                    "transitive": True,
                }
            ],
            "configured Artifacts pane",
        ),
        (
            [
                {
                    "name": "parents",
                    "kind": "hierarchy",
                    "label": "Parents",
                    "source": "status",
                    "directed": True,
                    "transitive": True,
                    "color": "red",
                }
            ],
            "unknown ref.relations",
        ),
    ],
)
def test_invalid_provider_relations_degrade_contract(
    relations: list[object],
    message: str,
) -> None:
    result = compile_provider_contract(
        kind="notes",
        label="Note",
        icon="¶",
        accent="#5FAFFF",
        spec=_document_spec(relations=relations),
        provider_spec_digest="bad-rel",
    )
    assert result.error is not None
    assert message in result.error
    assert result.error_code == "invalid_ref_relations"
    assert result.contract.has(PaneCapability.REFRESH)
    assert not result.contract.has(PaneCapability.RELATIONS)


@pytest.mark.parametrize(
    ("grouping", "message"),
    [
        ({"modes": "by_status"}, "modes"),
        (
            {
                "default_mode": "by_status",
                "modes": [
                    {
                        "id": "by_status",
                        "label": "Status",
                        "keys": ["missing"],
                    }
                ],
            },
            "undeclared ref.properties",
        ),
        (
            {
                "default_mode": "by_missing",
                "modes": [{"id": "by_status", "label": "Status", "keys": ["status"]}],
            },
            "default_mode",
        ),
        (
            {
                "default_mode": "by_status",
                "modes": [
                    {
                        "id": "by_status",
                        "label": "Status",
                        "keys": ["status"],
                        "renderer": "special",
                    }
                ],
            },
            "unknown ref.grouping.modes",
        ),
    ],
)
def test_invalid_provider_grouping_degrades_contract(
    grouping: dict[str, object],
    message: str,
) -> None:
    result = compile_provider_contract(
        kind="notes",
        label="Note",
        icon="¶",
        accent="#5FAFFF",
        spec=_document_spec(grouping=grouping),
        provider_spec_digest="bad-grouping",
    )
    assert result.error is not None
    assert message in result.error
    assert result.error_code == "invalid_ref_grouping"
    assert result.contract.has(PaneCapability.REFRESH)
    assert not result.contract.has(PaneCapability.GROUPING)


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


def test_presentation_digest_is_sensitive_to_the_query_profile() -> None:
    base = compile_provider_contract(
        kind="notes",
        label="Note",
        icon="¶",
        accent="#5FAFFF",
        spec=_document_spec(),
        provider_spec_digest="def",
    ).contract
    changed = compile_provider_contract(
        kind="notes",
        label="Note",
        icon="¶",
        accent="#5FAFFF",
        spec=_document_spec(properties={"body": {"type": "string"}}),
        provider_spec_digest="def",
    ).contract
    assert base.query_profile.digest != changed.query_profile.digest
    assert base.presentation_digest != changed.presentation_digest


def test_extract_provider_suppressions_accepts_valid_block() -> None:
    suppressions, error, code = extract_provider_suppressions(
        _document_spec(capabilities={"suppress": {"versions": "no history"}})
    )
    assert error is None
    assert code is None
    assert suppressions == {"versions": "no history"}


def test_extract_provider_relations_accepts_valid_block() -> None:
    relations, error, code = extract_provider_relations(
        "notes",
        _document_spec(
            relations=[
                {
                    "name": "beads",
                    "kind": "link",
                    "label": "Beads",
                    "source": "status",
                    "target_pane": "beads",
                    "inverse": "notes",
                    "directed": True,
                    "transitive": False,
                }
            ]
        ),
        configured_pane_ids=("beads", "ref:notes"),
    )
    assert error is None
    assert code is None
    assert relations[0].name == "beads"
    assert relations[0].target_pane == "beads"


def test_extract_provider_grouping_accepts_valid_block() -> None:
    grouping, error, code = extract_provider_grouping(
        _document_spec(
            grouping={
                "default_mode": "by_status",
                "modes": [{"id": "by_status", "label": "Status", "keys": ["status"]}],
            },
        )
    )
    assert error is None
    assert code is None
    assert grouping.default_mode == "by_status"
    assert grouping.modes[0].keys == ("status",)


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
