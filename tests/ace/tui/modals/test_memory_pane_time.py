"""Tests for card time stepping (phase `card-stepping`).

Covers the pager's moment model as the Memory card uses it: every step
intent and boundary against a fake timeline with hidden versions, a
dirty now, and a deleted subject, plus the atomic pin-apply path
(last-wins generation guard) and the footer-verb filter.
"""

from __future__ import annotations

from types import SimpleNamespace

from sase.ace.tui.keymaps.app_keymaps import MemoryPanelKeymaps
from sase.ace.tui.modals.memory_pane_time import (
    _moment_for_card,
    _parse_past_note,
    _step_boundary_notice,
    _step_destination,
    step_footer_verbs,
)


def _row(ordinal: int, **override: object) -> dict:
    base: dict = {
        "ordinal": ordinal,
        "commit": f"{ordinal:040d}",
        "committer_time": 1790085780,
        "class": "authored",
        "hidden": False,
        "summary": {"words_added": 3, "words_removed": 1},
        "provenance": {"agent": "athena", "bead": "sase-1ev.4"},
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


def test_older_from_now_lands_on_newest() -> None:
    timeline = _timeline(_row(1), _row(2), _row(3))
    moment = _moment_for_card(timeline, subject_id="note:x", pin_ordinal=0)
    assert moment is not None
    assert _step_destination(moment, "older") == 3


def test_older_skips_hidden_versions() -> None:
    timeline = _timeline(_row(1), _row(2, hidden=True), _row(3))
    moment = _moment_for_card(timeline, subject_id="note:x", pin_ordinal=3)
    assert moment is not None
    assert _step_destination(moment, "older") == 1


def test_newer_from_newest_returns_to_now() -> None:
    timeline = _timeline(_row(1), _row(2))
    moment = _moment_for_card(timeline, subject_id="note:x", pin_ordinal=2)
    assert moment is not None
    assert _step_destination(moment, "newer") == 0


def test_first_and_now_intents() -> None:
    timeline = _timeline(_row(1), _row(2), _row(3))
    moment = _moment_for_card(timeline, subject_id="note:x", pin_ordinal=2)
    assert moment is not None
    assert _step_destination(moment, "first") == 1
    assert _step_destination(moment, "now") == 0


def test_boundaries_return_none_with_pager_notice() -> None:
    timeline = _timeline(_row(1), _row(2))
    oldest = _moment_for_card(timeline, subject_id="note:x", pin_ordinal=1)
    assert oldest is not None
    assert _step_destination(oldest, "older") is None
    assert "v1" in _step_boundary_notice(oldest, "older")
    assert _step_destination(oldest, "first") is None

    now = _moment_for_card(timeline, subject_id="note:x", pin_ordinal=0)
    assert now is not None
    assert _step_destination(now, "newer") is None
    assert _step_destination(now, "now") is None
    assert "now" in _step_boundary_notice(now, "newer").lower()


def test_single_version_has_no_destinations() -> None:
    timeline = _timeline(_row(1))
    now = _moment_for_card(timeline, subject_id="note:x", pin_ordinal=0)
    assert now is not None
    assert _step_destination(now, "older") == 1
    only = _moment_for_card(timeline, subject_id="note:x", pin_ordinal=1)
    assert only is not None
    assert _step_destination(only, "older") is None
    assert _step_destination(only, "newer") == 0


def test_no_history_yields_no_moment() -> None:
    assert _moment_for_card(_timeline(), subject_id="note:x", pin_ordinal=0) is None
    assert _moment_for_card(None, subject_id="note:x", pin_ordinal=0) is None
    assert _moment_for_card("nope", subject_id="note:x", pin_ordinal=0) is None  # type: ignore[arg-type]


def test_dirty_now_marks_worktree() -> None:
    timeline = _timeline(_row(1), _row(2), dirty=True)
    moment = _moment_for_card(timeline, subject_id="note:x", pin_ordinal=0)
    assert moment is not None
    assert moment.worktree_dirty is True
    assert _step_destination(moment, "older") == 2


def test_deleted_row_is_tombstone_moment() -> None:
    timeline = _timeline(_row(1), _row(2, **{"class": "deleted"}))
    moment = _moment_for_card(timeline, subject_id="note:x", pin_ordinal=2)
    assert moment is not None
    assert moment.kind == "deleted"


def test_footer_verbs_show_only_steps() -> None:
    timeline = _timeline(_row(1), _row(2), _row(3))
    moment = _moment_for_card(timeline, subject_id="note:x", pin_ordinal=2)
    assert moment is not None
    verbs = step_footer_verbs(moment, keymaps=MemoryPanelKeymaps())
    assert verbs == ("( v1", ") v3", "} now", "= diff", "@")


def test_footer_verbs_use_configured_keys() -> None:
    timeline = _timeline(_row(1), _row(2))
    moment = _moment_for_card(timeline, subject_id="note:x", pin_ordinal=1)
    assert moment is not None
    keymaps = MemoryPanelKeymaps(history_older="<", history_newer=">", history_now="~")
    verbs = step_footer_verbs(moment, keymaps=keymaps)
    assert verbs == ("> v2", "~ now", "= diff", "@")


def test_parse_past_note_reads_past_frontmatter() -> None:
    node = SimpleNamespace(note=SimpleNamespace(relative_path="gotchas.md"))
    past = _parse_past_note(
        node,
        "---\ntype: core\ndescription: Old words.\n---\n\nBody then.\n",
    )
    assert past is not None
    assert past.description == "Old words."
    assert "Body then." in past.body
    assert "---" not in past.body


def _stub_mixin(**state: object) -> SimpleNamespace:
    """Return a stub carrying the real step-application methods."""
    from sase.ace.tui.modals.memory_pane_time import MemoryPaneTimeMixin

    stub = SimpleNamespace(
        _time_pins={},
        _time_applied={},
        _time_pending={},
        _time_bodies={},
        _time_request=None,
        _time_generation=0,
        _closed=False,
        is_mounted=True,
        notices=[],
        renders=0,
    )
    for name in (
        "_apply_step_intent",
        "_apply_time_pin",
        "_ensure_time_body",
        "_on_time_body_state_changed",
        "_remember_time_body",
    ):
        setattr(stub, name, getattr(MemoryPaneTimeMixin, name).__get__(stub))
    for key, value in state.items():
        setattr(stub, key, value)
    return stub


def _node() -> SimpleNamespace:
    return SimpleNamespace(identity="sase/memory/gotchas.md", strand=None)


def test_apply_step_caches_hit_applies_atomically() -> None:
    timeline = _timeline(_row(1), _row(2), _row(3))
    key = ("project:sase", "sase/memory/gotchas.md")
    stub = _stub_mixin()
    stub.notify = lambda message, **kwargs: stub.notices.append(str(message))  # type: ignore[attr-defined]
    stub._render_note_card = lambda: setattr(stub, "renders", stub.renders + 1)  # type: ignore[attr-defined]
    stub._prefetch_time_bodies = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    stub._time_bodies[(key[0], key[1], 2)] = {"body": "old words"}
    moment = _moment_for_card(timeline, subject_id="note:x", pin_ordinal=3)
    assert moment is not None
    # Pretend the card shows v3 with its body cached.
    stub._time_pins[key] = 3
    stub._time_applied[key] = 3
    stub._time_bodies[(key[0], key[1], 3)] = {"body": "new words"}
    from sase.ace.tui.modals.memory_pane_time import MemoryPaneTimeMixin

    MemoryPaneTimeMixin._apply_step_intent(
        stub,  # type: ignore[arg-type]
        key,
        _node(),
        timeline,
        moment,
        "older",
    )
    # Cache hit on v2: pin and applied move together, no worker needed.
    assert stub._time_pins[key] == 2
    assert stub._time_applied[key] == 2
    assert stub._time_request is None
    assert stub.notices == []


def test_apply_step_boundary_toasts_without_moving() -> None:
    timeline = _timeline(_row(1), _row(2))
    key = ("project:sase", "sase/memory/gotchas.md")
    stub = _stub_mixin()
    stub.notify = lambda message, **kwargs: stub.notices.append(str(message))  # type: ignore[attr-defined]
    from sase.ace.tui.modals.memory_pane_time import MemoryPaneTimeMixin

    moment = _moment_for_card(timeline, subject_id="note:x", pin_ordinal=1)
    assert moment is not None
    MemoryPaneTimeMixin._apply_step_intent(
        stub,  # type: ignore[arg-type]
        key,
        _node(),
        timeline,
        moment,
        "older",
    )
    assert key not in stub._time_pins
    assert len(stub.notices) == 1 and "v1" in stub.notices[0]


def test_stale_body_worker_is_dropped_last_wins() -> None:
    key = ("project:sase", "sase/memory/gotchas.md")
    stub = _stub_mixin()
    stub.notify = lambda message, **kwargs: stub.notices.append(str(message))  # type: ignore[attr-defined]
    stub._render_note_card = lambda: setattr(stub, "renders", stub.renders + 1)  # type: ignore[attr-defined]
    stub._selected_row = lambda: None  # type: ignore[attr-defined]
    from types import SimpleNamespace as _NS

    from textual.worker import WorkerState

    from sase.ace.tui.modals.memory_pane_time import MemoryPaneTimeMixin

    applied: list[int] = []
    stub._apply_time_pin = lambda k, n, ordinal: applied.append(ordinal)  # type: ignore[attr-defined]
    # A newer step already won: the stale worker result must not apply.
    stub._time_request = (key[0], key[1], 3, 9)
    event = _NS(
        state=WorkerState.SUCCESS,
        worker=_NS(result=(key[0], key[1], 2, 7, {"body": "x"})),
    )
    MemoryPaneTimeMixin._on_time_body_state_changed(stub, event)  # type: ignore[arg-type]
    assert applied == []
    assert stub.renders == 0


def test_step_keymap_defaults_cover_all_step_keys() -> None:
    from dataclasses import fields

    from sase.ace.tui.keymaps.bindings import build_memory_bindings

    keymaps = MemoryPanelKeymaps()
    assert (keymaps.history_older, keymaps.history_newer) == ("(", ")")
    assert (keymaps.history_first, keymaps.history_now) == ("{", "}")
    actions = {binding.action for binding in build_memory_bindings(keymaps)}
    assert {"history_older", "history_newer", "history_first", "history_now"} <= actions
    assert {field.name for field in fields(MemoryPanelKeymaps)} >= {
        "history_older",
        "history_newer",
        "history_first",
        "history_now",
    }


def _pinned_stub(applied: int) -> SimpleNamespace:
    """Return a stub whose selected row displays version *applied*."""
    from sase.ace.tui.modals.memory_pane_time import MemoryPaneTimeMixin

    stub = SimpleNamespace(notices=[], _time_pins={}, _time_applied={})
    stub._selected_row = lambda: _node()  # type: ignore[attr-defined]
    stub._time_applied_ordinal = lambda _node: applied  # type: ignore[attr-defined]
    stub.notify = lambda message, **_kw: stub.notices.append(str(message))  # type: ignore[attr-defined]
    for name in ("_refuse_while_pinned", "_refuse_link_while_pinned"):
        setattr(stub, name, getattr(MemoryPaneTimeMixin, name).__get__(stub))
    return stub


def test_pinned_card_refuses_edits_and_links() -> None:
    from sase.ace.tui.modals.memory_pane_time import PIN_EDIT_REFUSAL

    pinned = _pinned_stub(3)
    assert pinned._refuse_while_pinned() is True
    assert pinned._refuse_link_while_pinned() is True
    assert pinned.notices == [
        PIN_EDIT_REFUSAL,
        "links are as of now · H follows them at v3",
    ]

    now = _pinned_stub(0)
    assert now._refuse_while_pinned() is False
    assert now._refuse_link_while_pinned() is False
    assert now.notices == []


def test_mutating_actions_stop_while_pinned() -> None:
    """``a``, ``e``, ``d``, and ``I`` all stop at the past-edit guard."""
    from sase.ace.tui.modals.memory_panel_actions import MemoryPanelActionsMixin

    pushed: list[object] = []
    stub = SimpleNamespace(
        _loading=False,
        _write_busy=False,
        _ring=("sase",),
        app=SimpleNamespace(push_screen=lambda *args, **_kw: pushed.append(args)),
    )
    stub._refuse_while_pinned = lambda: True  # type: ignore[attr-defined]

    def _unexpected() -> None:
        raise AssertionError("guarded action ran past the pin refusal")

    stub._current_scope = _unexpected  # type: ignore[attr-defined]
    stub._selected_row = _unexpected  # type: ignore[attr-defined]
    for action in (
        "action_add_note",
        "action_edit_note",
        "action_delete_note",
        "action_publish",
    ):
        getattr(MemoryPanelActionsMixin, action)(stub)
    assert pushed == []


def test_past_strand_writes_no_audited_read() -> None:
    """A strand shown in the past records no read; at now it still does."""
    from sase.ace.tui.modals.memory_pane_loading import MemoryPaneLoadingMixin

    strand_node = SimpleNamespace(
        identity="glossary:alpha",
        strand=SimpleNamespace(slug="alpha"),
        web=SimpleNamespace(slug="glossary"),
    )
    workers: list[str] = []

    def _stub(applied: int) -> SimpleNamespace:
        stub = SimpleNamespace(
            _ring=(SimpleNamespace(key="sase"),),
            _scope_index=0,
            _strand_read_status={},
            _strand_read_worker=None,
            _strand_read_worker_identity=None,
        )
        stub._selected_row = lambda: strand_node  # type: ignore[attr-defined]
        stub._time_applied_ordinal = lambda _node: applied  # type: ignore[attr-defined]
        stub.run_worker = lambda *_args, **kwargs: workers.append(kwargs["group"])  # type: ignore[attr-defined]
        return stub

    past = _stub(2)
    MemoryPaneLoadingMixin._ensure_strand_read_for_current_selection(past)  # type: ignore[arg-type]
    assert workers == []
    assert past._strand_read_status == {}

    now = _stub(0)
    MemoryPaneLoadingMixin._ensure_strand_read_for_current_selection(now)  # type: ignore[arg-type]
    assert workers == ["memory-panel-strand-read"]
    assert now._strand_read_status == {"glossary:alpha": "pending"}


def test_pin_reresolves_after_timeline_change() -> None:
    """A surviving pin holds across a rebuild; a vanished one returns to now."""
    from sase.ace.tui.modals.memory_pane_time import MemoryPaneTimeMixin

    key = ("project:sase", "sase/memory/gotchas.md")
    stub = _stub_mixin()
    stub.notify = lambda message, **_kw: stub.notices.append(str(message))  # type: ignore[attr-defined]
    stub._render_note_card = lambda: setattr(stub, "renders", stub.renders + 1)  # type: ignore[attr-defined]
    stub._time_pins[key] = 2
    stub._time_applied[key] = 2

    grown = _timeline(_row(1), _row(2), _row(3), _row(4))
    MemoryPaneTimeMixin._reresolve_time_pin(stub, key, _node(), grown)  # type: ignore[arg-type]
    assert stub._time_pins[key] == 2
    assert stub._time_applied[key] == 2
    assert stub.notices == []

    rewritten = _timeline(_row(1))
    MemoryPaneTimeMixin._reresolve_time_pin(stub, key, _node(), rewritten)  # type: ignore[arg-type]
    assert key not in stub._time_pins
    assert key not in stub._time_applied
    assert stub.notices == ["that version is gone · back at now"]
    assert stub.renders == 1


def test_past_and_tombstone_card_heads_name_the_age() -> None:
    """The pinned head reads ``⟲ PAST · vK of N   <age>`` like the pager."""
    from sase.ace.tui.modals.memory_pane_time_strip import (
        TimeStripSnapshot,
        render_card_head,
    )
    from sase.pager.history_kit import history_styles_for_theme

    now = 1790769600
    day = 86400
    rows = [
        _row(1, committer_time=now - 30 * day),
        _row(2, committer_time=now - 10 * day),
    ]
    styles = history_styles_for_theme(None)

    past_timeline = _timeline(*rows, _row(3, committer_time=now - day))
    past = _moment_for_card(past_timeline, subject_id="note:x", pin_ordinal=2)
    snapshot = TimeStripSnapshot(
        subject_id="note:x",
        path_label="sase/memory/gotchas.md",
        timeline=past_timeline,
        now_epoch=now,
    )
    head = render_card_head(
        "sase/memory/gotchas.md", snapshot, styles, width=90, moment=past
    ).plain
    assert "PAST · v2 of 3" in head
    assert head.rstrip().endswith("10d")

    gone_timeline = _timeline(
        *rows, _row(3, committer_time=now - 2 * day, **{"class": "deleted"})
    )
    gone = _moment_for_card(gone_timeline, subject_id="note:x", pin_ordinal=3)
    head = render_card_head(
        "sase/memory/gotchas.md",
        TimeStripSnapshot(
            subject_id="note:x",
            path_label="sase/memory/gotchas.md",
            timeline=gone_timeline,
            now_epoch=now,
        ),
        styles,
        width=90,
        moment=gone,
    ).plain
    assert "DELETED · v3" in head
    assert head.rstrip().endswith("2d")
