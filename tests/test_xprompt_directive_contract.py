"""Coverage for the shared runtime directive contract."""

from __future__ import annotations

from typing import Any

import sase_core_rs

from sase.xprompt._directive_types import (
    _DIRECTIVE_ALIASES,
    _KNOWN_DIRECTIVES,
    _MULTI_VALUE_DIRECTIVES,
    AUTO_COMPATIBILITY_ARGUMENT_SUGGESTIONS,
)
from sase.xprompt.effort import EFFORT_LEVELS_ORDERED

_SPECIAL_RUNTIME_DIRECTIVES = frozenset({"alt", "xprompts_enabled"})


def test_runtime_directive_vocabulary_matches_core_contract() -> None:
    contract = _contract_by_name()
    runtime_names = set(_KNOWN_DIRECTIVES) | set(_SPECIAL_RUNTIME_DIRECTIVES)
    core_names = set(contract)
    extra = core_names - runtime_names

    assert extra == set()
    assert runtime_names <= core_names
    expected_aliases = {
        alias: name
        for alias, name in _DIRECTIVE_ALIASES.items()
        if name in runtime_names
    }
    expected_aliases["q"] = "queue"
    assert _contract_aliases(contract) == expected_aliases
    assert {
        name for name, row in contract.items() if bool(row["allows_multiple"])
    } == set(_MULTI_VALUE_DIRECTIVES) | {"alt", "xprompts_enabled", "queue"}
    assert _contract_keywords(contract) == {
        "alt": (),
        "auto": (),
        "clan": ("summary", "summary_script", "tribe"),
        "dispatch": (),
        "effort": (),
        "final": (),
        "hide": (),
        "id": ("bead", "clan", "family", "tribe"),
        "model": (),
        "repeat": (),
        "wait": ("agent", "bead", "proc", "time", "unit"),
        "queue": ("capacity", "p", "priority", "w", "weight"),
        "if": (),
        "proc": (
            "bash",
            "python",
            "timeout",
            "idle_timeout",
            "cwd",
            "workspace",
            "label",
        ),
        "xprompts_enabled": (),
    }
    assert contract["model"]["dynamic_keyword_role"] == "model_alias_key"
    assert (
        _suggested_values(contract["auto"]) == AUTO_COMPATIBILITY_ARGUMENT_SUGGESTIONS
    )
    assert _suggested_values(contract["effort"]) == tuple(EFFORT_LEVELS_ORDERED)
    assert _suggested_values(contract["repeat"]) == ("2", "3")
    assert _suggested_values(contract["xprompts_enabled"]) == ("false", "true")
    assert _contract_syntax_forms(contract) == {
        "alt": ("brace_shorthand", "colon", "parenthesized"),
        "auto": ("colon", "bare", "plus"),
        "clan": ("colon", "parenthesized"),
        "dispatch": ("colon", "parenthesized"),
        "effort": ("colon",),
        "final": ("colon", "parenthesized"),
        "hide": ("bare", "plus"),
        "id": ("colon", "parenthesized", "bare"),
        "model": ("colon", "parenthesized"),
        "repeat": ("colon",),
        "wait": ("colon", "parenthesized", "bare"),
        "queue": ("colon", "parenthesized"),
        "if": ("double_colon",),
        "proc": ("parenthesized", "double_colon"),
        "xprompts_enabled": ("colon",),
    }
    assert contract["if"]["feature_flag"] == "typed_launch_units"
    assert contract["proc"]["feature_flag"] == "typed_launch_units"
    assert contract["queue"].get("feature_flag") is None
    assert contract["queue"]["alias"] == "q"
    assert _suggested_values(contract["queue"]) == ("0", "1")
    assert contract["dispatch"].get("feature_flag") is None
    assert contract["if"]["body_kind"] == "fenced_code"
    assert contract["proc"]["body_kind"] == "optional_fenced_code"


def _contract_by_name() -> dict[str, dict[str, Any]]:
    rows = sase_core_rs.directive_contract()
    return {str(row["name"]): row for row in rows}


def _contract_aliases(contract: dict[str, dict[str, Any]]) -> dict[str, str]:
    return {
        str(row["alias"]): name
        for name, row in contract.items()
        if isinstance(row.get("alias"), str) and row["alias"]
    }


def _contract_keywords(
    contract: dict[str, dict[str, Any]],
) -> dict[str, tuple[str, ...]]:
    return {
        name: tuple(str(keyword["name"]) for keyword in row["keywords"])
        for name, row in contract.items()
    }


def _contract_syntax_forms(
    contract: dict[str, dict[str, Any]],
) -> dict[str, tuple[str, ...]]:
    return {
        name: tuple(str(syntax) for syntax in row["syntax_forms"])
        for name, row in contract.items()
    }


def _suggested_values(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(item["value"])
        for item in row.get("positional_suggestions", [])
        if isinstance(item, dict)
    )
