"""Tests for the sticky card word-diff view (phase `card-diff`).

Covers the pager's endpoint rules as the Memory card uses them through
``card_moment_for_view(..., view="diff")``: past, clean now, dirty now,
first version, tombstone, and hidden-version skipping. Plus the sticky
flag (toggle/reset), the last-wins diff worker guard, the
comparison-failure read fallback, the never-cache-now memo rule, and
the ``H`` view carry.
"""

from __future__ import annotations

from types import SimpleNamespace

from sase.ace.tui.keymaps.app_keymaps import MemoryPanelKeymaps
from sase.ace.tui.modals.memory_pane_diff import DIFF_UNAVAILABLE, MemoryPaneDiffMixin
from sase.ace.tui.modals.memory_pane_time import card_moment_for_view, step_footer_verbs


def _row(ordinal: int, **override: object) -> dict:
    base: dict = {
        "ordinal": ordinal,
        "commit": f"{ordinal:040d}",
        "committer_time": 1790085780,
        "class": "authored",
        "hidden": False,
        "summary": {"words_added": 3, "words_removed": 1},
        "provenance": {"agent": "athena", "bead": "sase-1ev.5"},
        "cause": {},
        "path": "sase/memory/gotchas.md",
        "blob_oid": f"blob{ordinal}",
    }
    base.update(override)
    return base


def _timeline(*rows: dict, **override: object) -> dict:
    base: dict = {
        "selector": "sase/memory/gotchas.md",
        "scope_key": "project:sase",
        "state": "tracked",
        "versions": list(rows),
        "total": len(rows),
        "dirty": False,
    }
    base.update(override)
    return base


def _diff_endpoints(timeline: dict, pin_ordinal: int) -> tuple[int, int] | None:
    moment = card_moment_for_view(
        timeline, subject_id="note:x", pin_ordinal=pin_ordinal, view="diff"
    )
    assert moment is not None
    diff = getattr(moment, "diff", None)
    assert diff is not None
    return (int(diff[0]), int(diff[1]))


def test_past_diff_compares_parent_to_pin() -> None:
    timeline = _timeline(_row(1), _row(2), _row(3))
    assert _diff_endpoints(timeline, 2) == (1, 2)


def test_clean_now_diff_shows_latest_change() -> None:
    timeline = _timeline(_row(1), _row(2), _row(3))
    assert _diff_endpoints(timeline, 0) == (2, 3)


def test_dirty_now_diff_compares_head_to_worktree() -> None:
    timeline = _timeline(_row(1), _row(2), _row(3), dirty=True)
    assert _diff_endpoints(timeline, 0) == (3, 0)


def test_first_version_diffs_against_empty() -> None:
    timeline = _timeline(_row(1))
    assert _diff_endpoints(timeline, 1) == (0, 1)


def test_tombstone_diff_is_the_deletion_summary() -> None:
    timeline = _timeline(_row(1), _row(2, **{"class": "deleted"}))
    assert _diff_endpoints(timeline, 2) == (1, 2)


def test_diff_endpoints_skip_hidden_versions() -> None:
    timeline = _timeline(_row(1), _row(2, hidden=True), _row(3))
    assert _diff_endpoints(timeline, 3) == (1, 3)
    assert _diff_endpoints(timeline, 0) == (1, 3)


def test_publish_loop_endpoints() -> None:
    """Edit → uncommitted → publish moves the diff endpoints forward."""
    clean = _timeline(_row(1), _row(2), _row(3))
    assert _diff_endpoints(clean, 0) == (2, 3)
    dirty = _timeline(_row(1), _row(2), _row(3), dirty=True)
    assert _diff_endpoints(dirty, 0) == (3, 0)
    published = _timeline(_row(1), _row(2), _row(3), _row(4))
    assert _diff_endpoints(published, 0) == (3, 4)


def test_footer_names_read_in_diff_view() -> None:
    timeline = _timeline(_row(1), _row(2), _row(3))
    moment = card_moment_for_view(
        timeline, subject_id="note:x", pin_ordinal=2, view="diff"
    )
    assert moment is not None
    verbs = step_footer_verbs(moment, keymaps=MemoryPanelKeymaps())
    assert verbs == ("( v1", ") v3", "} now", "= read", "@")


def test_footer_diff_verb_uses_configured_key() -> None:
    timeline = _timeline(_row(1), _row(2))
    moment = card_moment_for_view(
        timeline, subject_id="note:x", pin_ordinal=1, view="diff"
    )
    assert moment is not None
    keymaps = MemoryPanelKeymaps(history_toggle_diff="!")
    verbs = step_footer_verbs(moment, keymaps=keymaps)
    assert verbs[-2] == "! read"
    assert verbs[-1] == "@"


def test_footer_timeline_verb_uses_configured_key() -> None:
    timeline = _timeline(_row(1), _row(2))
    moment = card_moment_for_view(
        timeline, subject_id="note:x", pin_ordinal=1, view="read"
    )
    assert moment is not None
    keymaps = MemoryPanelKeymaps(history_timeline="T")
    verbs = step_footer_verbs(moment, keymaps=keymaps)
    assert verbs[-1] == "T"


def _stub_mixin(timelines: dict | None = None, **state: object) -> SimpleNamespace:
    """Return a stub carrying the real diff methods over fake siblings."""
    key = ("project:sase", "sase/memory/gotchas.md")
    timelines = timelines or {}
    stub = SimpleNamespace(
        _time_diff_view=False,
        _time_diffs={},
        _diff_failed=set(),
        _diff_request=None,
        _diff_generation=0,
        _diff_worker=None,
        _loading=False,
        _closed=False,
        is_mounted=True,
        _history_failed=set(),
        _history_latest=dict(timelines),
        _time_pins={},
        _time_applied={},
        notices=[],
        renders=0,
    )
    stub._time_key = lambda node: key  # type: ignore[attr-defined]
    stub._selected_row = lambda: SimpleNamespace(identity=key[1])  # type: ignore[attr-defined]
    stub._time_timeline = lambda node: (  # type: ignore[attr-defined]
        dict(stub._history_latest[key]) if key in stub._history_latest else None
    )
    stub._time_subject_id = lambda node: "note:x"  # type: ignore[attr-defined]
    stub._time_applied_ordinal = lambda node: int(stub._time_applied.get(key, 0))  # type: ignore[attr-defined]
    stub._time_pinned_ordinal = lambda node: int(stub._time_pins.get(key, 0))  # type: ignore[attr-defined]
    stub._time_strip_styles = lambda: None  # type: ignore[attr-defined]
    stub.notify = lambda message, **kwargs: stub.notices.append(str(message))  # type: ignore[attr-defined]
    stub._render_note_card = lambda: setattr(stub, "renders", stub.renders + 1)  # type: ignore[attr-defined]
    for name in (
        "_diff_view_on",
        "_reset_diff_view",
        "_drop_diff_state_for_scope",
        "_diff_endpoints",
        "_diff_ready_for_node",
        "_diff_overlay_for_node",
        "_diff_text_for_node",
        "_remember_diff",
        "_ensure_diff",
        "_on_diff_state_changed",
        "_prefetch_diff_comparisons",
        "_history_diff_carry",
        "action_history_toggle_diff",
    ):
        setattr(stub, name, getattr(MemoryPaneDiffMixin, name).__get__(stub))
    for attr, value in state.items():
        setattr(stub, attr, value)
    return stub


def _now_timeline() -> dict:
    return _timeline(_row(1), _row(2), _row(3))


def test_toggle_flips_sticky_view_and_resets_on_open() -> None:
    key = ("project:sase", "sase/memory/gotchas.md")
    stub = _stub_mixin(timelines={key: _now_timeline()})
    stub._time_diffs[(key[0], key[1], 2, 3)] = {
        "comparison": {"unified_diff": ""},
        "body": "words",
    }
    stub.run_worker = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("no worker on memo hit")
    )  # type: ignore[attr-defined]
    stub.action_history_toggle_diff()
    assert stub._time_diff_view is True
    assert stub.renders == 1
    # Sticky across selections: a second toggle turns it back off.
    stub.action_history_toggle_diff()
    assert stub._time_diff_view is False
    # Opening the pane resets the choice to read.
    stub._time_diff_view = True
    stub._reset_diff_view()
    assert stub._time_diff_view is False


def test_toggle_during_indexing_flips_without_worker() -> None:
    stub = _stub_mixin()
    spawned: list[str] = []
    stub.run_worker = lambda *args, **kwargs: spawned.append("worker")  # type: ignore[attr-defined]
    stub.action_history_toggle_diff()
    assert stub._time_diff_view is True
    assert spawned == []
    assert stub.renders == 1


def test_comparison_failure_keeps_read_view_and_toasts() -> None:
    from textual.worker import WorkerState

    key = ("project:sase", "sase/memory/gotchas.md")
    stub = _stub_mixin(timelines={key: _now_timeline()})
    stub._time_diff_view = True
    stub._diff_request = (key[0], key[1], 2, 3, 1)
    event = SimpleNamespace(
        state=WorkerState.SUCCESS,
        worker=SimpleNamespace(result=(key[0], key[1], 2, 3, 1, None, None, "boom")),
    )
    stub._on_diff_state_changed(event)
    assert stub.notices == [DIFF_UNAVAILABLE]
    assert (key[0], key[1], 2, 3) in stub._diff_failed
    assert stub.renders == 1
    # The sticky choice survives: the read view renders instead.
    assert stub._time_diff_view is True
    assert stub._diff_ready_for_node(SimpleNamespace(identity=key[1])) is None


def test_stale_diff_worker_is_dropped_last_wins() -> None:
    from textual.worker import WorkerState

    key = ("project:sase", "sase/memory/gotchas.md")
    stub = _stub_mixin(timelines={key: _now_timeline()})
    stub._time_diff_view = True
    stub._diff_request = (key[0], key[1], 2, 3, 9)
    event = SimpleNamespace(
        state=WorkerState.SUCCESS,
        worker=SimpleNamespace(
            result=(key[0], key[1], 2, 3, 7, {"unified_diff": ""}, "words", None)
        ),
    )
    stub._on_diff_state_changed(event)
    assert stub.renders == 0
    assert stub._time_diffs == {}


def test_now_pairs_are_never_memoized() -> None:
    stub = _stub_mixin()
    stub._remember_diff(("s", "sel", 3, 0), {"unified_diff": ""}, "words")
    stub._remember_diff(("s", "sel", 0, 1), {"unified_diff": ""}, "words")
    assert stub._time_diffs == {}
    stub._remember_diff(("s", "sel", 1, 2), {"unified_diff": "x"}, "words")
    assert stub._time_diffs[("s", "sel", 1, 2)] == {
        "comparison": {"unified_diff": "x"},
        "body": "words",
    }


def test_drop_diff_state_for_scope() -> None:
    key = ("project:sase", "sase/memory/gotchas.md")
    stub = _stub_mixin()
    stub._time_diffs[(key[0], key[1], 1, 2)] = {"comparison": {}, "body": "x"}
    stub._diff_failed.add((key[0], key[1], 1, 2))
    stub._diff_request = (key[0], key[1], 1, 2, 1)
    stub._drop_diff_state_for_scope("project:sase")
    assert stub._time_diffs == {}
    assert stub._diff_failed == set()
    assert stub._diff_request is None


def test_history_carry_passes_view_and_base() -> None:
    key = ("project:sase", "sase/memory/gotchas.md")
    stub = _stub_mixin(timelines={key: _now_timeline()})
    assert stub._history_diff_carry() == ("read", None)
    stub._time_diff_view = True
    stub._time_applied[key] = 2
    stub._time_pins[key] = 2
    assert stub._history_diff_carry() == ("diff", "v1")
    stub._time_applied.pop(key)
    stub._time_pins.pop(key)
    assert stub._history_diff_carry() == ("diff", "v2")


def test_build_diff_body_renders_card_wire() -> None:
    from sase.pager.history_kit import build_diff_body

    built = build_diff_body(
        {"unified_diff": "@@ -1 +1 @@\n-old words\n+new words\n"},
        "new words\n",
        history_styles=None,
    )
    assert "new words" in built.text.plain
    empty = build_diff_body({}, "same\n", history_styles=None)
    assert "no changes" in empty.text.plain


def test_diff_keymap_defaults_cover_toggle_diff() -> None:
    from dataclasses import fields

    from sase.ace.tui.keymaps.bindings import build_memory_bindings

    keymaps = MemoryPanelKeymaps()
    assert keymaps.history_toggle_diff == "="
    actions = {binding.action for binding in build_memory_bindings(keymaps)}
    assert "history_toggle_diff" in actions
    assert {field.name for field in fields(MemoryPanelKeymaps)} >= {
        "history_toggle_diff"
    }
