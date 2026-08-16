"""Validation coverage for artifact provider contract declarations."""

from __future__ import annotations

import pytest

from sase.ace.tui._artifact_tab_contract import compile_provider_contract
from sase.ace.tui._artifact_tab_contract_provider import (
    extract_provider_grouping,
    extract_provider_relations,
    extract_provider_suppressions,
)
from sase.ace.tui._artifact_tab_model import PaneCapability

from .contract_compiler_support import document_spec


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
        spec=document_spec(capabilities=capabilities),  # type: ignore[arg-type]
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
        spec=document_spec(relations=relations),
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
        spec=document_spec(grouping=grouping),
        provider_spec_digest="bad-grouping",
    )
    assert result.error is not None
    assert message in result.error
    assert result.error_code == "invalid_ref_grouping"
    assert result.contract.has(PaneCapability.REFRESH)
    assert not result.contract.has(PaneCapability.GROUPING)


def test_extract_provider_suppressions_accepts_valid_block() -> None:
    suppressions, error, code = extract_provider_suppressions(
        document_spec(capabilities={"suppress": {"versions": "no history"}})
    )
    assert error is None
    assert code is None
    assert suppressions == {"versions": "no history"}


def test_extract_provider_relations_accepts_valid_block() -> None:
    relations, error, code = extract_provider_relations(
        "notes",
        document_spec(
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
        document_spec(
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
