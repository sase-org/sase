"""Option-query parser and v2 model contract coverage."""

from __future__ import annotations

import pytest

from sase.notification_gates.models import GateError, GateSpec
from sase.notification_gates.query import GateQueryError, parse_gate_query


@pytest.mark.parametrize(
    ("query", "canonical", "branches"),
    [
        ("approve", "approve", (("approve",),)),
        (
            "approve AND commit OR reject OR feedback",
            "(approve AND commit) OR reject OR feedback",
            (("approve", "commit"), ("reject",), ("feedback",)),
        ),
        (
            " ( approve AND commit )OR reject ",
            "(approve AND commit) OR reject",
            (("approve", "commit"), ("reject",)),
        ),
    ],
)
def test_parse_gate_query_normalizes_precedence_and_parentheses(
    query: str,
    canonical: str,
    branches: tuple[tuple[str, ...], ...],
) -> None:
    parsed = parse_gate_query(query)

    assert parsed.query == canonical
    assert parsed.branches == branches


@pytest.mark.parametrize(
    ("query", "message", "position"),
    [
        ("", "at least one option", 0),
        ("approve OR", "after OR", 10),
        ("approve AND", "after AND", 11),
        ("()", "at least one option", 1),
        ("(approve OR reject)", "OR may not appear", 9),
        ("((approve))", "Expected an option", 1),
        ("approve OR approve", "appears more than once", 11),
        ("Approve", "Unexpected character", 0),
    ],
)
def test_parse_gate_query_reports_positional_errors(
    query: str, message: str, position: int
) -> None:
    with pytest.raises(GateQueryError, match=message) as exc_info:
        parse_gate_query(query)

    assert exc_info.value.position == position


def _option(option_id: str, label: str) -> dict[str, object]:
    return {
        "id": option_id,
        "label": label,
        "command": {"argv": [f"commands/{option_id}"]},
    }


def _spec() -> dict[str, object]:
    approve = _option("approve", "Approve")
    approve["icon"] = "✅"
    return {
        "schema_version": 2,
        "kind": "custom",
        "query": " approve AND commit OR reject ",
        "options": [
            approve,
            _option("commit", "Commit"),
            _option("reject", "Reject"),
        ],
        "groups": [
            {
                "options": ["commit", "approve"],
                "label": "Ship",
                "icon": "✅",
            }
        ],
        "resources": [
            {
                "path": f"commands/{option_id}",
                "role": "command",
                "content": "#!/bin/sh\nprintf '{}\\n'\n",
            }
            for option_id in ("approve", "commit", "reject")
        ],
    }


def test_gate_spec_normalizes_group_members_to_query_order() -> None:
    spec = GateSpec.from_mapping(_spec())

    assert spec.query == "(approve AND commit) OR reject"
    assert spec.branches == (("approve", "commit"), ("reject",))
    assert spec.groups[0].options == ("approve", "commit")
    assert spec.groups[0].label == "Ship"
    assert spec.groups[0].icon == "✅"
    assert all(option.default_selected for option in spec.options)


def test_gate_spec_defaults_group_control_to_first_option() -> None:
    value = _spec()
    value["groups"] = []

    spec = GateSpec.from_mapping(value)

    assert spec.groups[0].label == "Approve"
    assert spec.groups[0].icon == "✅"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda value: value.update(query="approve OR missing"), "unknown_option"),
        (lambda value: value.update(query="approve OR commit"), "unreferenced_option"),
        (
            lambda value: value.update(groups=[{"options": ["approve", "reject"]}]),
            "invalid_group",
        ),
        (lambda value: value.update(groups=[{"options": []}]), "invalid_group"),
    ],
)
def test_gate_spec_rejects_query_option_and_group_mismatches(
    mutation: object, code: str
) -> None:
    value = _spec()
    assert callable(mutation)
    mutation(value)

    with pytest.raises(GateError) as exc_info:
        GateSpec.from_mapping(value)

    assert exc_info.value.code == code


def test_gate_spec_rejects_v1_with_v2_shape_guidance() -> None:
    value = _spec()
    value["schema_version"] = 1
    value["choices"] = value.pop("options")

    with pytest.raises(GateError) as exc_info:
        GateSpec.from_mapping(value)

    assert exc_info.value.code == "unsupported_schema"
    assert "query, options, and optional groups" in str(exc_info.value)
    assert "choices/extras are unsupported" in str(exc_info.value)
