"""Completion-extras tests for the ``:`` Command Line (sase-17x.10).

Covers the completion-extras phase contract: the FOR-row derivation, the
doc-peek width threshold, ``ctrl+r`` ranking, and marked-row insertion,
plus the empty-state RECENT rows, variadic-slot detection, and the
provider-unavailable footer note.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.command_line.extras import (
    doc_peek_for_highlight,
    _doc_peek_text,
    doc_peek_visible,
    empty_state_hint,
    empty_state_rows,
    _first_required_positional_kind,
    _for_selection_rows,
    _iter_leaf_paths,
    marked_insert_text,
    marked_values_for_kind,
    provider_unavailable_note,
    rank_history_entries,
    _recent_rows,
    relative_age,
    slot_is_variadic,
)
from sase.core.time import get_timezone


def _entry(
    line: str, *, last_used: str = "", last_exit: int | None = None
) -> SimpleNamespace:
    return SimpleNamespace(line=line, last_used=last_used, last_exit=last_exit)


def _stamp(**kwargs: Any) -> str:
    # ``relative_age`` reads stamps as configured-zone wall time, so the
    # stamps must come from that zone too, not from the host's clock.
    moment = datetime.now(get_timezone()) - timedelta(**kwargs)
    return moment.strftime("%y%m%d_%H%M%S")


# -- relative age ------------------------------------------------------------


def test_relative_age_buckets() -> None:
    """Stamps render as ``30s/5m/2h/1d ago`` like the panel mock."""
    assert relative_age(_stamp(seconds=30)).endswith("s ago")
    assert relative_age(_stamp(minutes=5)) == "5m ago"
    assert relative_age(_stamp(hours=2)) == "2h ago"
    assert relative_age(_stamp(days=1)) == "1d ago"
    assert relative_age("bogus") == ""
    assert relative_age("") == ""


# -- RECENT rows --------------------------------------------------------------


def test_recent_rows_carry_age_and_exit_mark() -> None:
    """RECENT rows show the newest entries with age and ✓/✗ marks."""
    rows = _recent_rows(
        [
            _entry("bead list", last_used=_stamp(hours=2), last_exit=0),
            _entry(
                "agent wait x --timeout 10m", last_used=_stamp(days=1), last_exit=124
            ),
            _entry("bead show y", last_used=_stamp(minutes=3), last_exit=None),
        ]
    )
    assert [row.display for row in rows] == [
        "bead list",
        "agent wait x --timeout 10m",
        "bead show y",
    ]
    assert rows[0].description == "2h ago  ✓"
    assert rows[1].description == "1d ago  ✗ 124"
    assert rows[2].description == "3m ago"
    assert all(row.badge == "recent" for row in rows)
    assert all("insert_text" in row.to_item() for row in rows)


def test_recent_rows_skip_blanks_and_cap_at_five() -> None:
    """Blank lines never become rows; the list caps at five."""
    rows = _recent_rows([_entry(f"cmd {index}") for index in range(8)] + [_entry("  ")])
    assert len(rows) == 5


# -- FOR-row derivation -------------------------------------------------------


def _help_tree() -> dict[tuple[str, ...], dict[str, Any]]:
    def _leaf(
        name: str,
        positionals: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "usage": f"sase ... {name}",
            "summary": f"{name} things",
            "positionals": positionals or [],
            "options": [],
            "children": [],
        }

    bead_id = {
        "metavar": "ID",
        "dest": "id",
        "required": True,
        "value_kind": "bead",
        "choices": None,
    }
    agent_name = {
        "metavar": "NAME",
        "dest": "name",
        "required": True,
        "value_kind": "agent",
        "choices": None,
    }
    return {
        (): {
            "children": [{"name": "bead"}, {"name": "agent"}],
            "positionals": [],
            "options": [],
        },
        ("bead",): {
            "children": [{"name": "close"}, {"name": "list"}],
            "positionals": [],
            "options": [],
        },
        ("agent",): {
            "children": [{"name": "show"}],
            "positionals": [],
            "options": [],
        },
        ("bead", "close"): _leaf("close", [bead_id]),
        ("bead", "list"): _leaf("list"),
        ("agent", "show"): _leaf("show", [agent_name]),
    }


def _lookup(
    tree: dict[tuple[str, ...], dict[str, Any]],
) -> Callable[[list[str]], dict[str, Any] | None]:
    def _help(path: list[str]) -> dict[str, Any] | None:
        return tree.get(tuple(path))

    return _help


def test_iter_leaf_paths_skips_groups() -> None:
    """Only commands with no subcommands come back as leaves."""
    assert _iter_leaf_paths(_lookup(_help_tree())) == [
        ["bead", "close"],
        ["bead", "list"],
        ["agent", "show"],
    ]


def test_iter_leaf_paths_empty_without_root() -> None:
    """A missing root degrades to no rows instead of raising."""
    assert _iter_leaf_paths(lambda path: None) == []


def test_first_required_positional_kind() -> None:
    """The first required positional decides the leaf's entity kind."""
    tree = _help_tree()
    assert _first_required_positional_kind(tree[("bead", "close")]) == "bead"
    assert _first_required_positional_kind(tree[("bead", "list")]) is None
    assert _first_required_positional_kind(None) is None


def test_for_rows_match_selected_kind_ranked_by_usage() -> None:
    """FOR rows list kind-matching leaves, most-used first."""
    entries = [
        _entry("bead close sase-1"),
        _entry("bead close sase-2"),
        _entry("agent show athena.1"),
    ]
    rows = _for_selection_rows(
        _lookup(_help_tree()), "bead", "sase-9", entries, limit=5
    )
    assert [row.display for row in rows] == ["bead close sase-9"]
    assert rows[0].insert_text == "bead close sase-9"
    assert rows[0].badge == "suggest"


def test_for_rows_empty_without_selection() -> None:
    """No selection (or no value) means no FOR rows."""
    tree_lookup = _lookup(_help_tree())
    assert _for_selection_rows(tree_lookup, None, "sase-9", []) == []
    assert _for_selection_rows(tree_lookup, "bead", None, []) == []
    assert _for_selection_rows(tree_lookup, "proc", "abc", []) == []


def test_empty_state_rows_stack_recent_then_for() -> None:
    """RECENT rows come first, then the derived FOR rows."""
    entries = [_entry("bead list", last_used=_stamp(hours=2), last_exit=0)]
    rows = empty_state_rows(
        _lookup(_help_tree()),
        entries,
        selected_kind="agent",
        selected_value="athena.1",
    )
    assert [row.display for row in rows] == ["bead list", "agent show athena.1"]


def test_empty_state_hint_counts_commands() -> None:
    """The empty hint names the command count, like the panel mock."""
    assert (
        empty_state_hint(63)
        == "63 commands · type to search · ⇥ complete · ; Command Palette"
    )
    assert (
        empty_state_hint(1)
        == "1 command · type to search · ⇥ complete · ; Command Palette"
    )
    assert empty_state_hint() == "type to search · ⇥ complete · ; Command Palette"


# -- doc peek -----------------------------------------------------------------


def test_doc_peek_visible_only_on_wide_terminals() -> None:
    """The card needs 140 columns; narrow terminals use the signature row."""
    assert doc_peek_visible(140) is True
    assert doc_peek_visible(160) is True
    assert doc_peek_visible(139) is False
    assert doc_peek_visible(None) is False


def test_doc_peek_text_covers_summary_usage_and_defaults() -> None:
    """The card shows summary, usage, arguments, choices, and defaults."""
    card = _doc_peek_text(
        {
            "summary": "Close a bead",
            "usage": "sase bead close ‹ID…› [-n NOTE]",
            "positionals": [
                {"metavar": "ID", "dest": "id", "required": True, "choices": None}
            ],
            "options": [
                {
                    "strings": ["-R", "--resolution"],
                    "summary": "Resolution",
                    "choices": ["done", "canceled"],
                    "default": "done",
                }
            ],
            "children": [],
        },
        name="bead close",
    )
    assert "Close a bead" in card
    assert "sase bead close" in card
    assert "choices: done, canceled" in card
    assert "default: done" in card
    assert _doc_peek_text(None, name="bead close") == ""


def test_doc_peek_for_highlight_subcommand_and_option() -> None:
    """Subcommand rows peek the child; option rows peek the option."""
    lookup = _lookup(_help_tree())
    card = doc_peek_for_highlight(
        completion_kind="subcommand",
        highlighted={"display": "close", "badge": "cmd"},
        path=["bead"],
        help_lookup=lookup,
    )
    assert "close things" in card
    option_card = doc_peek_for_highlight(
        completion_kind="option_name",
        highlighted={"insert_text": "--resolution", "badge": "RESOLUTION"},
        path=["bead", "close"],
        help_lookup=lambda path: {
            "summary": "",
            "usage": "",
            "positionals": [],
            "options": [
                {
                    "strings": ["--resolution"],
                    "summary": "Resolution",
                    "choices": None,
                    "default": None,
                }
            ],
            "children": [],
        },
    )
    assert "Resolution" in option_card
    assert (
        doc_peek_for_highlight(
            completion_kind="positional",
            highlighted={"display": "sase-1", "badge": "bead"},
            path=["bead", "close"],
            help_lookup=lookup,
        )
        == ""
    )


# -- ctrl+r history search ----------------------------------------------------


def test_rank_history_orders_by_fuzzy_match_with_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stubbed matcher proves the ordering (tier first, then recency)."""
    import sase.core.fuzzy_facade as facade
    from sase.core.fuzzy_facade import FuzzyMatch

    def _stub(query: str, text: str) -> FuzzyMatch | None:
        if "bead" in text:
            return FuzzyMatch(tier=0, score=10, runs=((0, 1),))
        if "agent" in text:
            return FuzzyMatch(tier=1, score=1, runs=((0, 1),))
        return None

    monkeypatch.setattr(facade, "fuzzy_match", _stub)
    ranked = rank_history_entries(
        "bead",
        [
            _entry("agent show athena.1"),
            _entry("bead list --status open"),
            _entry("unrelated line"),
        ],
    )
    assert [item.line for item in ranked] == [
        "bead list --status open",
        "agent show athena.1",
    ]
    assert ranked[0].match_runs == [[0, 1]]


def test_rank_history_through_rust_matcher() -> None:
    """The shared Rust matcher ranks an exact-prefix hit first."""
    try:
        from sase.core.rust import require_rust_extension

        require_rust_extension()
    except ImportError:
        pytest.skip("sase_core_rs is not importable in this environment")
    ranked = rank_history_entries(
        "bead cl",
        [_entry("agent show x"), _entry("bead close sase-1")],
    )
    assert [item.line for item in ranked] == ["bead close sase-1"]
    assert ranked[0].match_runs


def test_rank_history_blank_query_returns_entries_in_order() -> None:
    """An empty query lists history newest-first without matching."""
    entries = [_entry("b one"), _entry("a two")]
    assert [item.line for item in rank_history_entries("", entries)] == [
        "b one",
        "a two",
    ]


# -- marked rows and variadic slots -------------------------------------------


def _variadic_help() -> dict[str, Any]:
    return {
        "positionals": [
            {
                "metavar": "ID",
                "dest": "id",
                "required": True,
                "nargs": "+",
                "is_remainder": False,
            }
        ],
        "options": [
            {"dest": "tag", "strings": ["--tag"], "repeatable": True},
            {"dest": "note", "strings": ["-n"], "repeatable": False},
        ],
        "children": [],
    }


def test_slot_is_variadic_from_help() -> None:
    """Repeatable options and ``+`` positionals (or remainders) are variadic."""
    lookup = lambda path: _variadic_help()  # noqa: E731
    assert (
        slot_is_variadic(
            {"kind": "positional", "dest": "id"}, lookup, ["bead", "close"]
        )
        is True
    )
    assert (
        slot_is_variadic(
            {"kind": "option_value", "dest": "tag"}, lookup, ["bead", "close"]
        )
        is True
    )
    assert (
        slot_is_variadic(
            {"kind": "option_value", "dest": "note"}, lookup, ["bead", "close"]
        )
        is False
    )
    assert (
        slot_is_variadic({"kind": "remainder", "dest": ""}, lookup, ["proc", "run"])
        is True
    )
    assert slot_is_variadic({"kind": "subcommand", "dest": ""}, lookup, []) is False
    assert slot_is_variadic(None, lookup, []) is False


def test_marked_values_read_pane_targets() -> None:
    """Marked patch targets resolve to sorted values; other kinds stay empty."""
    from sase.core.artifact_entry_target import ArtifactEntryTarget

    target = ArtifactEntryTarget(pane_id="patches", parts=("sase-2",))
    other = ArtifactEntryTarget(pane_id="patches", parts=("sase-1",))
    app = SimpleNamespace(
        _artifacts_marked_targets={"patches": {target, other}, "agents": set()}
    )
    assert marked_values_for_kind(app, "patch") == ["sase-1", "sase-2"]
    assert marked_values_for_kind(app, "agent") == []
    assert marked_values_for_kind(app, "proc") == []
    assert marked_values_for_kind(None, "patch") == []


def test_marked_agent_values_read_agents_tab_mark_order() -> None:
    """Agent slots follow the Agents tab's explicit mark order."""
    first = ("running", "athena.1", None)
    second = ("running", "mus.2", None)
    app = SimpleNamespace(
        _marked_agent_order=[second, first],
        _agents_with_children=[
            SimpleNamespace(identity=first, agent_name="athena.1"),
            SimpleNamespace(identity=second, agent_name="mus.2"),
        ],
    )
    assert marked_values_for_kind(app, "agent") == ["mus.2", "athena.1"]


def test_marked_insert_text_quotes_and_trails_space() -> None:
    """The marked row fills the slot: quoted values plus a trailing space."""
    assert marked_insert_text(["sase-1", "sase-2"]) == "sase-1 sase-2 "
    assert marked_insert_text(["two words"]) == "'two words' "
    assert marked_insert_text([]) == ""


# -- provider health -----------------------------------------------------------


def test_provider_unavailable_note() -> None:
    """Empty or failed providers show the subtle footer note."""
    assert provider_unavailable_note("bead") == "⚠ bead unavailable"
    assert provider_unavailable_note(None) == "⚠ value unavailable"
