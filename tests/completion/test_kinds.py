"""Tests for sase.completion.kinds."""

from __future__ import annotations

import argparse
from typing import Any

from sase.completion.kinds import (
    NAME_TABLE,
    PATH_OVERRIDES,
    ValueKind,
    resolve_value_kind,
    set_completion_kind,
)


def _option_action(flag: str, **kwargs: Any) -> argparse.Action:
    parser = argparse.ArgumentParser()
    return parser.add_argument(flag, **kwargs)


def _positional_action(name: str, **kwargs: Any) -> argparse.Action:
    parser = argparse.ArgumentParser()
    return parser.add_argument(name, **kwargs)


def test_explicit_override_wins_over_everything() -> None:
    action = _option_action("--project")
    set_completion_kind(action, ValueKind.TAG)
    assert resolve_value_kind(action, ("some", "path")) is ValueKind.TAG


def test_path_override_wins_over_name_table() -> None:
    action = _positional_action("id")
    assert "id" not in NAME_TABLE
    assert resolve_value_kind(action, ("bead", "show")) is ValueKind.BEAD


def test_path_override_does_not_apply_under_a_different_command() -> None:
    action = _positional_action("id")
    assert resolve_value_kind(action, ("monitor", "show")) is None


def test_name_table_resolves_unambiguous_dest() -> None:
    action = _option_action("--project")
    assert resolve_value_kind(action, ("bead", "list")) is ValueKind.PROJECT


def test_name_table_resolves_catalog_dests() -> None:
    expected = {
        "--agent": ValueKind.AGENT,
        "--model": ValueKind.MODEL,
        "--tag": ValueKind.TAG,
        "--skill": ValueKind.SKILL,
        "--patch": ValueKind.PATCH,
        "--plan": ValueKind.PLAN,
        "--workspace": ValueKind.WORKSPACE,
    }
    for flag, kind in expected.items():
        dest = flag.removeprefix("--")
        action = _option_action(flag, dest=dest)
        assert resolve_value_kind(action, ("any", "path")) is kind, flag


def test_metavar_resolves_when_dest_does_not() -> None:
    action = _positional_action("plan_file", metavar="PLAN_FILE")
    assert resolve_value_kind(action, ()) is ValueKind.PATH


def test_unresolvable_action_returns_none() -> None:
    action = _option_action("--totally-unknown-flag")
    assert resolve_value_kind(action, ()) is None


def test_ambiguous_bare_names_are_not_in_name_table() -> None:
    for ambiguous in ("id", "name", "query", "reference", "refs", "selector"):
        assert ambiguous not in NAME_TABLE


def test_bead_show_id_path_override_present() -> None:
    assert PATH_OVERRIDES[(("bead", "show"), "id")] is ValueKind.BEAD


def test_path_overrides_cover_shipped_catalog_slots() -> None:
    assert PATH_OVERRIDES[(("bead", "close"), "ids")] is ValueKind.BEAD
    assert PATH_OVERRIDES[(("patch", "status"), "name")] is ValueKind.PATCH
    assert PATH_OVERRIDES[(("agent", "show"), "name")] is ValueKind.AGENT
    assert PATH_OVERRIDES[(("xprompt", "show"), "name")] is ValueKind.XPROMPT
    assert PATH_OVERRIDES[(("skill", "use"), "name")] is ValueKind.SKILL
    assert PATH_OVERRIDES[(("plan", "show"), "target")] is ValueKind.PLAN
    assert PATH_OVERRIDES[(("bead", "ref", "add"), "refs")] is ValueKind.ARTIFACT
    assert PATH_OVERRIDES[(("artifact", "show"), "reference")] is ValueKind.ARTIFACT
    assert PATH_OVERRIDES[(("glossary", "read"), "term")] is ValueKind.GLOSSARY
    assert PATH_OVERRIDES[(("glossary", "show"), "term")] is ValueKind.GLOSSARY
    assert PATH_OVERRIDES[(("glossary", "log"), "term")] is ValueKind.GLOSSARY
