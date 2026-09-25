"""Completion-popup tests for the ``:`` Command Line (sase-17x.9).

Covers the completion-popup phase contract: the Tab/Enter/Escape state
machine, stale async provider results dropped, selected-first ranking
through the Rust handle, highlight spans matching the resolver tokens,
and a keystroke path that never awaits.
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.ace.tui.command_line.popup import (
    CompletionPopupState,
    _longest_common_prefix,
    popup_footer,
    _render_popup_row,
)
from sase.ace.tui.command_line.screen_completion import (
    CommandLineScreenCompletionMixin,
)
from sase.ace.tui.command_line.signature import (
    _build_chips,
    _build_signature,
    _first_diagnostic_message,
    _option_summary_text,
    signature_hint_line,
)
from sase.ace.tui.command_line.sources import (
    ProviderCache,
    _in_memory_candidates,
    needs_provider_fetch,
    path_candidates,
    path_completion_request,
    selected_entity_values,
)


def _items(*insert_texts: str) -> list[dict]:
    return [
        {"insert_text": text, "display": text.strip(), "match_runs": []}
        for text in insert_texts
    ]


# -- longest common prefix -----------------------------------------------------


def test_longest_common_prefix() -> None:
    """LCP spans the shared stem and collapses on divergence."""
    assert _longest_common_prefix(["close ", "closed"]) == "close"
    assert _longest_common_prefix(["bead "]) == "bead "
    assert _longest_common_prefix(["abc", "xyz"]) == ""
    assert _longest_common_prefix([]) == ""


# -- Tab / Enter / Escape state machine ----------------------------------------


def test_tab_accepts_unique_candidate() -> None:
    """Tab with a single candidate inserts it without activating the menu."""
    state = CompletionPopupState()
    state.reset(_items("close "), typed_text="bead cl", replace_start=5, replace_end=7)
    decision = state.on_tab()
    assert decision.action == "accept"
    assert decision.text == "close "
    assert state.menu_active is False


def test_tab_inserts_longest_common_prefix_first() -> None:
    """Tab inserts the LCP before ever activating the menu."""
    state = CompletionPopupState()
    state.reset(
        _items("close ", "closed "),
        typed_text="bead cl",
        replace_start=5,
        replace_end=7,
    )
    decision = state.on_tab()
    assert decision.action == "complete-prefix"
    assert decision.text == "close"
    assert state.menu_active is False


def test_tab_activates_then_cycles() -> None:
    """Tab with no shared prefix activates the menu, then cycles rows."""
    state = CompletionPopupState()
    state.reset(
        _items("list ", "show "),
        typed_text="bead ",
        replace_start=5,
        replace_end=5,
    )
    assert state.on_tab().action == "activate"
    assert state.menu_active is True
    assert state.on_tab().action == "move"
    assert state.index == 1
    assert state.on_tab().action == "move"
    assert state.index == 0  # wraps around


def test_shift_tab_cycles_backward() -> None:
    """Shift-Tab activates the menu and walks rows in reverse."""
    state = CompletionPopupState()
    state.reset(
        _items("list ", "show "), typed_text="x", replace_start=0, replace_end=1
    )
    assert state.on_shift_tab().action == "activate"
    assert state.on_shift_tab().action == "move"
    assert state.index == 1  # wrapped backward from 0


def test_enter_accepts_when_active_submits_otherwise() -> None:
    """Enter accepts the highlight in the menu and runs the line outside it."""
    state = CompletionPopupState()
    state.reset(_items("close "), typed_text="bead cl", replace_start=5, replace_end=7)
    assert state.on_enter().action == "submit"
    state.on_tab()  # single item accepts...
    active = CompletionPopupState()
    active.reset(
        _items("list ", "show "), typed_text="x", replace_start=0, replace_end=1
    )
    active.on_tab()
    decision = active.on_enter()
    assert decision.action == "accept"
    assert decision.text == "list "


def test_escape_leaves_menu_and_restores_typed_text() -> None:
    """Escape in the menu restores the typed text; outside it propagates."""
    state = CompletionPopupState()
    state.reset(
        _items("list ", "show "), typed_text="bead l", replace_start=5, replace_end=6
    )
    assert state.on_escape().action == "propagate"
    state.on_tab()
    decision = state.on_escape()
    assert decision.action == "leave-menu"
    assert decision.text == "bead l"
    assert state.menu_active is False


def test_ctrl_n_and_ctrl_p_activate_and_move() -> None:
    """``ctrl+n`` / ``ctrl+p`` enter the menu and walk it."""
    state = CompletionPopupState()
    state.reset(
        _items("a ", "b ", "c "), typed_text="x", replace_start=0, replace_end=1
    )
    assert state.on_ctrl_n().action == "activate"
    assert state.on_ctrl_n().action == "move"
    assert state.index == 1
    assert state.on_ctrl_p().action == "move"
    assert state.index == 0


def test_empty_popup_keys_are_noops() -> None:
    """An empty popup consumes nothing and moves nowhere."""
    state = CompletionPopupState()
    assert state.on_tab().action == "none"
    assert state.on_enter().action == "submit"
    assert state.on_escape().action == "propagate"


# -- stale async results dropped ------------------------------------------------


def test_provider_cache_drops_stale_generations() -> None:
    """Only the latest keystroke generation may commit provider results."""
    cache = ProviderCache(ttl_seconds=60.0)
    first = cache.next_generation()
    second = cache.next_generation()
    assert cache.commit(first, "bead", "sase", [{"value": "old"}]) is False
    assert cache.cached("bead", "sase") is None
    assert cache.commit(second, "bead", "sase", [{"value": "new"}]) is True
    assert cache.cached("bead", "sase") == [{"value": "new"}]


def test_provider_cache_entries_expire() -> None:
    """Expired entries read back as missing so the next keystroke refetches."""
    now = 100.0
    cache = ProviderCache(ttl_seconds=10.0, clock=lambda: now)
    generation = cache.next_generation()
    assert cache.commit(generation, "bead", None, [{"value": "x"}]) is True
    now += 5.0
    assert cache.cached("bead", None) == [{"value": "x"}]
    now += 6.0
    assert cache.cached("bead", None) is None


def test_needs_provider_fetch_uses_path_and_empty_entity_fallbacks() -> None:
    """Paths scan in a worker; empty entity state falls back to its provider."""
    assert needs_provider_fetch(None) is False
    assert needs_provider_fetch("") is False
    assert needs_provider_fetch("path") is True
    assert needs_provider_fetch("dir") is True
    assert needs_provider_fetch("agent") is False
    assert needs_provider_fetch("bead") is True
    assert needs_provider_fetch("proc", SimpleNamespace()) is True
    assert needs_provider_fetch("project", SimpleNamespace()) is True


# -- in-memory sources and selection -------------------------------------------


def _agents_app() -> SimpleNamespace:
    return SimpleNamespace(
        current_tab="agents",
        current_attempt_number=None,
        _agents=[
            SimpleNamespace(agent_name="athena.1", status="running"),
            SimpleNamespace(agent_name="mus.2", status="done"),
        ],
        _get_selected_agent=lambda: SimpleNamespace(
            agent_name="athena.1",
            phase_bead_id="sase-17x.9",
            bead_id=None,
            fleet_origin_alias=None,
            plan_path="/plans/202609/selected_agent_plan.md",
        ),
    )


def test_in_memory_agent_candidates_come_from_app_state() -> None:
    """Agent slots complete from the TUI's live agents without I/O."""
    candidates = _in_memory_candidates(_agents_app(), "agent")
    assert [candidate.value for candidate in candidates] == ["athena.1", "mus.2"]
    assert all(candidate.source == "tui" for candidate in candidates)
    assert _in_memory_candidates(_agents_app(), "bead") == []
    assert _in_memory_candidates(SimpleNamespace(), "agent") == []


def test_selected_entity_values_lead_with_selection() -> None:
    """The selected agent, plan, and linked bead rank first for ``selected=``."""
    values = selected_entity_values(_agents_app())
    assert values[0] == "athena.1"
    assert values[1] == "selected_agent_plan"
    assert "sase-17x.9" in values


def test_proc_and_project_candidates_read_live_app_state() -> None:
    """Proc projections and live agent project metadata populate their slots."""
    app = SimpleNamespace(
        _proc_projection=SimpleNamespace(
            rows=[
                SimpleNamespace(
                    proc_id="proc-17", label="check command", command=["just", "check"]
                )
            ]
        ),
        _agents=[SimpleNamespace(project_file="/projects/sase/sase.sase")],
    )
    proc_rows = _in_memory_candidates(app, "proc")
    project_rows = _in_memory_candidates(app, "project")
    assert [row.value for row in proc_rows] == ["proc-17"]
    assert proc_rows[0].description == "check command"
    assert [row.value for row in project_rows] == ["sase"]


def test_path_candidates_scan_one_requested_directory(tmp_path: Path) -> None:
    """Path candidates preserve the typed prefix and suffix directories."""
    (tmp_path / "child").mkdir()
    (tmp_path / "notes.md").write_text("notes")
    request = path_completion_request("work/", str(tmp_path))
    assert request.scan_directory == str(tmp_path / "work")
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "nested").mkdir()
    (tmp_path / "work" / "item.txt").write_text("item")
    rows = path_candidates(request, directories_only=False)
    assert [row["value"] for row in rows] == ["work/nested/", "work/item.txt"]
    assert [
        row["value"] for row in path_candidates(request, directories_only=True)
    ] == ["work/nested/"]


def test_cd_completion_includes_project_and_unpin_values() -> None:
    """The built-in ``cd`` slot uses project rows and exposes ``-`` unpinning."""
    screen = object.__new__(CommandLineScreenCompletionMixin)
    project_context = screen._cd_completion_context("cd +sa", len("cd +sa"))
    assert project_context is not None
    project_items = screen._complete_cd(
        "cd +sa",
        len("cd +sa"),
        project_context,
        [{"value": "sase", "badge": "project", "source": "tui"}],
    )
    assert [item["insert_text"] for item in project_items["items"]] == ["+sase"]

    unpin_context = screen._cd_completion_context("cd -", len("cd -"))
    assert unpin_context is not None
    unpin_items = screen._complete_cd("cd -", len("cd -"), unpin_context, [])
    assert [item["insert_text"] for item in unpin_items["items"]] == ["-"]


def test_dynamic_merge_layers_in_memory_before_cached_providers() -> None:
    """``complete(dynamic=…)`` gets TUI entities first, then provider rows."""
    from sase.ace.tui.command_line.sources import collect_dynamic_candidates

    cache = ProviderCache(ttl_seconds=60.0)
    generation = cache.next_generation()
    assert (
        cache.commit(
            generation, "bead", "sase", [{"value": "sase-1", "source": "provider"}]
        )
        is True
    )
    dynamic = collect_dynamic_candidates(_agents_app(), "bead", "sase", cache)
    assert dynamic[-1]["value"] == "sase-1"
    agents_only = collect_dynamic_candidates(_agents_app(), "agent", "sase", cache)
    assert [item["value"] for item in agents_only] == ["athena.1", "mus.2"]


def test_selected_first_ranking_through_rust_handle() -> None:
    """The Rust ranker marks selected entities so the popup shows ``sel``."""
    import json

    try:
        from sase.completion.build import build_spec
        from sase.completion.command_line_grammar import CommandLineGrammar

        spec = build_spec()
        grammar = CommandLineGrammar.from_spec_json(json.dumps(spec.to_json()))
    except AttributeError:
        pytest.skip(
            "installed sase_core_rs wheel predates CommandLineGrammar "
            "(sase-17x.5 pin not installed in this venv)"
        )
    dynamic = [
        {"value": "zzz-other", "description": "other agent", "badge": "agent"},
        {"value": "athena.1", "description": "selected agent", "badge": "agent"},
    ]
    completed = grammar.complete(
        "agent show ", len("agent show "), dynamic=dynamic, selected=["athena.1"]
    )
    by_value = {item["display"]: item for item in completed["items"]}
    assert by_value["athena.1"]["selected"] is True
    assert by_value["zzz-other"]["selected"] is False
    assert completed["items"][0]["display"] == "athena.1"


def test_popup_row_marks_selected_and_highlights_runs() -> None:
    """Selected rows get ``◆ … sel``; fuzzy runs render bold."""
    row = _render_popup_row(
        {
            "display": "athena.1",
            "match_runs": [[0, 3]],
            "badge": "agent",
            "description": "running",
            "source": "tui",
            "selected": True,
        }
    )
    plain = row.plain
    assert "◆" in plain
    assert "sel" in plain
    assert "athena.1" in plain
    assert "[agent]" in plain
    bold_spans = [span for span in row.spans if "bold" in str(span.style)]
    assert bold_spans, "match runs must be emphasized"


def test_popup_footer_format() -> None:
    """The footer reads ``<kind> · N of M · fuzzy`` plus the key hint."""
    footer = popup_footer("bead", 8, 410)
    assert footer == "bead · 8 of 410 · fuzzy    ⇥ complete"


# -- signature line --------------------------------------------------------------


def _signature_context() -> dict:
    return {
        "tokens": [],
        "argv": ["bead", "close"],
        "path": ["bead", "close"],
        "node_kind": "leaf",
        "slot": {},
        "used_dests": [],
        "diagnostics": [
            {
                "start": 0,
                "end": 4,
                "severity": "warning",
                "code": "unknown",
                "message": "unknown subcommand",
            }
        ],
        "signature": {
            "segments": [
                {"text": "bead", "role": "command", "active": False, "required": True},
                {"text": "close", "role": "command", "active": True, "required": True},
                {
                    "text": "‹ID…›",
                    "role": "positional",
                    "active": False,
                    "required": True,
                },
            ],
            "summary": "Close a bead",
        },
        "run_policy": {"policy": "proc", "note": None},
        "writes": True,
        "confirms": True,
        "confirm_flag_present": False,
        "stdin": False,
        "schema_version": 1,
    }


def test_signature_shows_active_slot_diagnostic_and_chips() -> None:
    """The hint row carries the segments, the diagnostic, and the chips."""
    line = signature_hint_line(_signature_context())
    plain = line.plain
    assert "bead" in plain and "close" in plain and "‹ID…›" in plain
    assert "unknown subcommand" in plain
    assert "⚠ writes" in plain
    assert "asks to confirm · -y" in plain


def test_signature_option_swap_replaces_slots() -> None:
    """A highlighted option swaps its summary (choices, default) into the row."""
    summary = _option_summary_text(
        {
            "summary": "Filter by status",
            "choices": ["open", "closed"],
            "default": "open",
            "repeatable": True,
            "mutex": None,
        }
    )
    assert "Filter by status" in summary
    assert "open, closed" in summary
    assert "default: open" in summary
    assert "repeatable" in summary
    line = signature_hint_line(
        _signature_context(),
        highlighted_option={"summary": "Filter by status", "choices": ["open"]},
    )
    assert "Filter by status" in line.plain
    assert "unknown subcommand" not in line.plain


def test_chips_cover_terminal_deny_and_stdin() -> None:
    """Foreground, deny, and stdin policies each render their own chip."""
    foreground = dict(_signature_context(), run_policy={"policy": "foreground"})
    assert "↗ terminal" in _build_chips(foreground).plain
    denied = dict(
        _signature_context(), run_policy={"policy": "deny", "note": "use edit"}
    )
    assert "⊘ use edit" in _build_chips(denied).plain
    assert "reads stdin" in _build_chips(dict(_signature_context(), stdin=True)).plain
    assert _build_chips(None).plain == ""
    assert _first_diagnostic_message(None) == ""
    assert _first_diagnostic_message({}) == ""
    assert _build_signature(None).plain == ""


# -- input highlight overlay -----------------------------------------------------


def test_highlight_spans_match_resolver_tokens() -> None:
    """Token roles and diagnostics land on the input overlay at token spans."""
    from sase.ace.tui.command_line.input import CommandLineInput

    widget = CommandLineInput()
    widget.text = "bead close --reason"
    widget.set_resolve_context(
        {
            "tokens": [
                {
                    "text": "bead",
                    "start": 0,
                    "end": 4,
                    "role": "command",
                    "quoted": False,
                    "unterminated": False,
                },
                {
                    "text": "--reason",
                    "start": 11,
                    "end": 19,
                    "role": "option",
                    "quoted": False,
                    "unterminated": False,
                },
            ],
            "diagnostics": [
                {
                    "start": 5,
                    "end": 10,
                    "severity": "warning",
                    "code": "x",
                    "message": "m",
                }
            ],
        }
    )
    spans = widget._highlights[0]
    by_style = {}
    for start, end, name in spans:
        by_style.setdefault(name, []).append((start, end))
    assert by_style["cmdline.command"] == [(0, 4)]
    assert by_style["cmdline.option"] == [(11, 19)]
    assert by_style["cmdline.diagnostic"] == [(5, 10)]


# -- keystroke path never awaits -------------------------------------------------


def test_keystroke_path_never_awaits() -> None:
    """Resolve, popup, and signature refresh stay synchronous (perf budget)."""
    import inspect

    from sase.ace.tui.command_line import screen as screen_module

    for name in (
        "_refresh_completion",
        "_complete_line",
        "on_text_area_changed",
        "command_line_handle_key",
    ):
        member = getattr(screen_module.CommandLineScreen, name)
        if name == "command_line_handle_key":
            assert inspect.iscoroutinefunction(member)
            continue
        assert not inspect.iscoroutinefunction(member), name
        assert "await" not in inspect.getsource(member), name
