"""Unit coverage for artifact contract compilation."""

from __future__ import annotations

import pytest

from sase.ace.query_profile import compiled_profile_for_builtin_pane
from sase.ace.tui._artifact_link_contract import ARTIFACT_LINK_RELATIONS
from sase.ace.tui import _artifact_tab_descriptions as descriptions
from sase.ace.tui._artifact_tab_contract import (
    GENERIC_DOCUMENT_COPY_TARGETS,
    PLAN_COPY_TARGETS,
    _presentation_digest,
    compile_builtin_contract,
    compile_provider_contract,
    contract_with_digit,
)
from sase.ace.tui._artifact_tab_contract_provider import provider_facts_from_spec
from sase.ace.tui._artifact_tab_model import PaneCapability, RelationKind
from sase.artifact_providers import builtin_plan_ref_provider_spec

from .contract_compiler_support import document_spec


def _artifact_link_relation_names() -> list[str]:
    return [item.name for item in ARTIFACT_LINK_RELATIONS]


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
    assert contract.has(PaneCapability.SHELL)
    assert contract.has(PaneCapability.STABLE_REFERENCE_COPY)
    assert contract.has(PaneCapability.FILTER_SESSION)
    assert contract.has(PaneCapability.RELATIONS)
    # Beads only implements the single-purpose epic-tree fold, not the
    # multi-mode ArtifactGroupFoldMixin protocol GROUPING promises, so it
    # must not claim the capability (sase-m6.9).
    if adapter == "beads":
        assert not contract.has(PaneCapability.GROUPING)
    else:
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
    if adapter in {"patches", "beads"}:
        assert contract.has(PaneCapability.STATUS_COUNTERS)
        assert contract.status_counters
    else:
        assert not contract.has(PaneCapability.STATUS_COUNTERS)
    if adapter == "beads":
        assert not contract.grouping.modes
    else:
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
        *_artifact_link_relation_names(),
    ]
    assert [item.kind for item in contract.relations] == [
        RelationKind.HIERARCHY,
        RelationKind.HIERARCHY,
        RelationKind.FAMILY,
        *([RelationKind.LINK] * len(_artifact_link_relation_names())),
    ]
    assert contract.grouping.default_mode == "by_project"
    assert [item.id for item in contract.grouping.modes] == [
        "by_project",
        "by_date",
        "by_status",
    ]


def test_stitches_contract_names_patches_not_plans() -> None:
    contract = compile_builtin_contract(
        "stitches",
        label="Stitch",
        icon="x",
        accent="#000000",
    )
    assert [item.name for item in contract.relations] == [
        "parents",
        "children",
        "patches",
        *_artifact_link_relation_names(),
    ]
    patches = next(item for item in contract.relations if item.name == "patches")
    assert patches.target_pane == "patches"
    assert patches.source == "stitch_patch_tag"


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
        spec=document_spec(),
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
        spec=document_spec(),
        provider_spec_digest="def",
    )
    assert result.error == "boom"
    assert result.error_code == "invalid_query_profile"
    assert result.contract.query_profile.fields == ()
    assert result.contract.query_profile.pane_id == "ref:notes"
    assert not result.contract.has(PaneCapability.FILTER_SESSION)


def test_provider_fact_extraction_from_schema_v1() -> None:
    spec = document_spec()
    facts = provider_facts_from_spec("notes", spec, is_degraded=False, suppressions={})
    assert facts.has_inventory is True
    assert facts.has_fields is True
    assert facts.has_stable_identity is True
    assert facts.has_revisions is False
    assert facts.can_mutate is False
    assert facts.is_plan_adapter is False

    empty = provider_facts_from_spec(
        "notes",
        document_spec(properties={}, inventory={"globs": []}),
        is_degraded=False,
        suppressions={},
    )
    assert empty.has_inventory is False
    assert empty.has_fields is False


def test_revision_property_earns_versions_fact() -> None:
    facts = provider_facts_from_spec(
        "notes",
        document_spec(
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
        *_artifact_link_relation_names(),
    ]


def test_unknown_document_provider_gets_generic_copy_targets() -> None:
    result = compile_provider_contract(
        kind="notes",
        label="Note",
        icon="¶",
        accent="#5FAFFF",
        spec=document_spec(),
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
    assert contract.has(PaneCapability.RELATIONS)
    assert [item.name for item in contract.relations] == [
        "bundle",
        *_artifact_link_relation_names(),
    ]
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
        spec=document_spec(
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
        spec=document_spec(
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
        spec=document_spec(
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
        spec=document_spec(),
        provider_spec_digest="def",
    ).contract
    changed = compile_provider_contract(
        kind="notes",
        label="Note",
        icon="¶",
        accent="#5FAFFF",
        spec=document_spec(properties={"body": {"type": "string"}}),
        provider_spec_digest="def",
    ).contract
    assert base.query_profile.digest != changed.query_profile.digest
    assert base.presentation_digest != changed.presentation_digest


def test_presentation_digest_is_sensitive_to_description_body_and_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    descriptions._configured_pane_descriptions_for_token.cache_clear()
    monkeypatch.setattr(descriptions, "current_config_token", lambda: ("provider",))
    monkeypatch.setattr(descriptions, "load_merged_config", lambda: {})
    base = compile_provider_contract(
        kind="notes",
        label="Note",
        icon="¶",
        accent="#5FAFFF",
        spec=document_spec(
            pane={
                "description": "Shared summary",
                "description_body": "Provider body",
            }
        ),
        provider_spec_digest="def",
    ).contract
    changed_body = compile_provider_contract(
        kind="notes",
        label="Note",
        icon="¶",
        accent="#5FAFFF",
        spec=document_spec(
            pane={
                "description": "Shared summary",
                "description_body": "Changed body",
            }
        ),
        provider_spec_digest="def",
    ).contract

    assert base.presentation_digest != changed_body.presentation_digest

    descriptions._configured_pane_descriptions_for_token.cache_clear()
    monkeypatch.setattr(descriptions, "current_config_token", lambda: ("config",))
    monkeypatch.setattr(
        descriptions,
        "load_merged_config",
        lambda: {
            "ace": {
                "artifacts": {
                    "panes": {
                        "ref:notes": {
                            "description": "Shared summary",
                            "description_body": "Provider body",
                        }
                    }
                }
            }
        },
    )
    same_text_config_source = compile_provider_contract(
        kind="notes",
        label="Note",
        icon="¶",
        accent="#5FAFFF",
        spec=document_spec(
            pane={
                "description": "Shared summary",
                "description_body": "Provider body",
            }
        ),
        provider_spec_digest="def",
    ).contract

    assert base.description == same_text_config_source.description
    assert base.description_body == same_text_config_source.description_body
    assert base.description_source == "provider"
    assert same_text_config_source.description_source == "config"
    assert base.presentation_digest != same_text_config_source.presentation_digest
