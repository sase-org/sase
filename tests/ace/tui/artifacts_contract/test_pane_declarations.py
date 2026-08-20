"""Declarative provider pane presentation contract tests."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui._artifact_tab_contract import (
    compile_builtin_contract,
    compile_provider_contract,
)
from sase.ace.tui._artifact_tab_descriptors import provider_descriptors
from sase.ace.tui._artifact_tab_model import (
    PaneCapability,
    ProjectProviderRecord,
)
from sase.sidecar_ref_config import SidecarRefPolicy


def _document_spec(
    *,
    kind: str = "notes",
    properties: dict[str, object] | None = None,
    pane: dict[str, object] | None = None,
) -> dict[str, object]:
    ref: dict[str, object] = {
        "kind": kind,
        "icon": "D",
        "expansion_format": "@{checkout_path}",
        "properties": properties
        if properties is not None
        else {
            "title": {"type": "string", "source": "markdown_frontmatter"},
            "status": {"type": "string", "source": "markdown_frontmatter"},
        },
        "detail": {"fields": ["title", "status"]},
        "identity": {},
        "inventory": {"globs": ["**/*.md"]},
        "publication": {
            "link": "vcs_permalink",
            "referenced_by": "markdown_table",
        },
    }
    if pane is not None:
        ref["pane"] = pane
    return {
        "schema_version": 1,
        "provider": kind,
        "ref": ref,
    }


def test_provider_pane_declaration_compiles_presentation_and_grouping() -> None:
    result = compile_provider_contract(
        kind="research",
        label="Research",
        icon="R",
        accent="#058D1D",
        spec=_document_spec(
            kind="research",
            properties={
                "updated_time": {
                    "type": "datetime",
                    "source": "markdown_frontmatter",
                },
                "status": {
                    "type": "enum",
                    "values": ["draft", "final"],
                    "source": "markdown_frontmatter",
                },
                "tags": {"type": "string_list", "source": "markdown_frontmatter"},
            },
            pane={
                "label": "Research",
                "description": "Research reports",
                "order": 40,
                "row": {
                    "title": "title",
                    "badges": ["status"],
                    "secondary": ["updated_time"],
                    "list_fields": ["tags"],
                },
                "default_sort": [{"field": "updated_time", "direction": "desc"}],
                "facets": ["status", "tags"],
                "group_by": "status",
                "empty_state": {
                    "title": "No research",
                    "body": "No research reports match.",
                },
            },
        ),
        provider_spec_digest="wire",
    )

    contract = result.contract
    assert result.error is None
    assert contract.label == "Research"
    assert contract.description == "Research reports"
    assert contract.order == 40
    assert contract.presentation.row.title == "title"
    assert contract.presentation.row.badges == ("status",)
    assert contract.presentation.row.secondary == ("updated_time",)
    assert contract.presentation.row.list_fields == ("tags",)
    assert contract.presentation.default_sort[0].field == "updated_time"
    assert contract.presentation.default_sort[0].direction == "desc"
    assert contract.presentation.facets == ("status", "tags")
    assert contract.empty_state.title == "No research"
    assert contract.grouping.default_mode == "by_status"
    assert contract.grouping.modes[0].keys == ("status",)
    status_field = contract.query_profile.field("status")
    assert status_field is not None
    assert status_field.value_kind == "enum"
    assert status_field.static_values == ("draft", "final")


def test_invalid_provider_pane_reference_degrades_contract() -> None:
    result = compile_provider_contract(
        kind="research",
        label="Research",
        icon="R",
        accent="#058D1D",
        spec=_document_spec(
            kind="research",
            pane={"row": {"badges": ["unsafe_callback"]}},
        ),
        provider_spec_digest="wire",
    )

    assert result.error is not None
    assert result.error_code == "invalid_ref_pane"
    assert "unsafe_callback" in result.error
    assert result.contract.has(PaneCapability.REFRESH)
    assert not result.contract.has(PaneCapability.FILTER_SESSION)


def test_compiled_artifact_panes_declare_artifact_link_relations() -> None:
    contracts = [
        compile_builtin_contract(adapter, label=adapter, icon="x", accent="#0")
        for adapter in ("stitches", "patches", "beads", "files")
    ]
    contracts.append(
        compile_provider_contract(
            kind="plan",
            label="Plan",
            icon="P",
            accent="#0",
            spec=None,
            provider_spec_digest="wire",
        ).contract
    )
    contracts.append(
        compile_provider_contract(
            kind="notes",
            label="Note",
            icon="N",
            accent="#0",
            spec=_document_spec(),
            provider_spec_digest="wire",
        ).contract
    )

    for contract in contracts:
        declarations = {item.name: item for item in contract.relations}
        assert declarations["links"].source == "artifact_links"
        assert declarations["links"].inverse == "linked_by"
        assert declarations["links"].directed is True
        assert declarations["linked_by"].source == "artifact_links"
        assert declarations["linked_by"].inverse == "links"
        assert declarations["linked_by"].transitive is False


def test_pane_only_changes_presentation_digest_not_query_profile() -> None:
    base = compile_provider_contract(
        kind="notes",
        label="Note",
        icon="N",
        accent="#5FAFFF",
        spec=_document_spec(),
        provider_spec_digest="wire",
    ).contract
    changed = compile_provider_contract(
        kind="notes",
        label="Note",
        icon="N",
        accent="#5FAFFF",
        spec=_document_spec(
            pane={
                "description": "Notes pane",
                "empty_state": {"body": "No matching notes."},
            },
        ),
        provider_spec_digest="wire",
    ).contract

    assert base.query_profile.digest == changed.query_profile.digest
    assert base.presentation_digest != changed.presentation_digest
    assert changed.description == "Notes pane"


def test_provider_descriptors_sort_declared_order_with_label_tie_break() -> None:
    descriptors = provider_descriptors(
        (
            ProjectProviderRecord(
                project="proj",
                display_name="Proj",
                workspace_dir="/tmp/proj",
                role="beta",
                root=Path("/tmp/proj/beta"),
                policy=SidecarRefPolicy(
                    role="beta",
                    ref_kind="beta",
                    is_document=True,
                    spec=_document_spec(
                        kind="beta",
                        pane={"label": "Beta", "order": 20},
                    ),
                ),
            ),
            ProjectProviderRecord(
                project="proj",
                display_name="Proj",
                workspace_dir="/tmp/proj",
                role="alpha",
                root=Path("/tmp/proj/alpha"),
                policy=SidecarRefPolicy(
                    role="alpha",
                    ref_kind="alpha",
                    is_document=True,
                    spec=_document_spec(
                        kind="alpha",
                        pane={"label": "Alpha", "order": 20},
                    ),
                ),
            ),
        )
    )

    assert [descriptor.label for descriptor in descriptors] == ["Alpha", "Beta"]
