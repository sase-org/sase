"""Tests for the canonical structured output-variable value model."""

from __future__ import annotations

import json
import math

import pytest

from sase.core.output_variable_values import (
    MAX_OUTPUT_VARIABLE_DEPTH,
    MAX_OUTPUT_VARIABLE_NODES,
    MAX_OUTPUT_VARIABLE_VALUE_BYTES,
    coerce_var_map,
    encode_var_value,
    normalize_var_value,
)


@pytest.mark.parametrize(
    "value",
    (
        "text",
        42,
        3.5,
        True,
        False,
        None,
        ["a", 2, False, None],
        {"z": [1, {"ok": True}], "a": {}},
    ),
)
def test_every_json_shape_round_trips(value: object) -> None:
    normalized = normalize_var_value("result", value)

    decoded = normalize_var_value("result", json.loads(encode_var_value(normalized)))
    assert decoded == normalized


def test_normalization_sorts_maps_preserves_lists_and_normalizes_nested_strings() -> (
    None
):
    value = {
        "z": ["first\r\nsecond", "tail"],
        "a\rkey": {"leaf": "x\ry"},
    }

    normalized = normalize_var_value("cfg", value)

    assert normalized == {
        "a\nkey": {"leaf": "x\ny"},
        "z": ["first\nsecond", "tail"],
    }
    assert list(normalized) == ["a\nkey", "z"]


def test_string_leaf_errors_name_the_nested_json_path() -> None:
    with pytest.raises(ValueError, match=r"findings\[1\]\.severity.*NUL"):
        normalize_var_value(
            "findings",
            [{"severity": "low"}, {"severity": "hi\x00gh"}],
        )

    oversized = "é" * (MAX_OUTPUT_VARIABLE_VALUE_BYTES // 2 + 1)
    with pytest.raises(ValueError, match=r"cfg\.labels\[0\].*8194.*8192"):
        normalize_var_value("cfg", {"labels": [oversized]})


def test_nested_map_keys_are_validated_and_normalized() -> None:
    with pytest.raises(ValueError, match="map key at cfg must not be empty"):
        normalize_var_value("cfg", {"": "value"})
    with pytest.raises(ValueError, match="map key at cfg must be a string"):
        normalize_var_value("cfg", {1: "value"})
    with pytest.raises(ValueError, match="map key at cfg.*NUL"):
        normalize_var_value("cfg", {"bad\x00key": "value"})

    oversized_key = "x" * (MAX_OUTPUT_VARIABLE_VALUE_BYTES + 1)
    with pytest.raises(ValueError, match="map key at cfg.*8193.*8192"):
        normalize_var_value("cfg", {oversized_key: "value"})


def test_bool_is_accepted_before_int_and_int64_is_bounded() -> None:
    assert normalize_var_value("flag", True) is True
    assert normalize_var_value("min", -(2**63)) == -(2**63)
    assert normalize_var_value("max", 2**63 - 1) == 2**63 - 1

    with pytest.raises(ValueError, match="too_small.*signed 64-bit"):
        normalize_var_value("too_small", -(2**63) - 1)
    with pytest.raises(ValueError, match="too_large.*signed 64-bit"):
        normalize_var_value("too_large", 2**63)


@pytest.mark.parametrize("value", (math.nan, math.inf, -math.inf))
def test_non_finite_numbers_are_rejected(value: float) -> None:
    with pytest.raises(ValueError, match="metric.*finite"):
        normalize_var_value("metric", value)


def test_depth_cap_accepts_boundary_and_rejects_next_level() -> None:
    value: object = "leaf"
    for _ in range(MAX_OUTPUT_VARIABLE_DEPTH):
        value = [value]
    assert normalize_var_value("tree", value) == value

    value = [value]
    with pytest.raises(ValueError, match=r"tree\[0\].*maximum depth 8"):
        normalize_var_value("tree", value)


def test_node_cap_counts_containers_and_leaves() -> None:
    accepted = [None] * (MAX_OUTPUT_VARIABLE_NODES - 1)
    assert normalize_var_value("items", accepted) == accepted

    rejected = [None] * MAX_OUTPUT_VARIABLE_NODES
    with pytest.raises(ValueError, match="1024-node limit"):
        normalize_var_value("items", rejected)


def test_encoded_size_cap_applies_to_the_whole_value() -> None:
    leaf = "x" * MAX_OUTPUT_VARIABLE_VALUE_BYTES
    assert normalize_var_value("payload", [leaf] * 7) == [leaf] * 7

    with pytest.raises(ValueError, match=r"payload.*encoded UTF-8 bytes.*65536"):
        normalize_var_value("payload", [leaf] * 8)


def test_coercion_drops_bad_entries_but_preserves_json_null() -> None:
    raw = {
        "null_value": None,
        "nested": {"ok": [1, True]},
        "bad": object(),
        "infinite": math.inf,
    }

    assert coerce_var_map(raw) == {
        "nested": {"ok": [1, True]},
        "null_value": None,
    }


def test_encoding_is_compact_unicode_and_sorted() -> None:
    assert encode_var_value({"z": "é", "a": [True, None]}) == (
        '{"a":[true,null],"z":"é"}'
    )
