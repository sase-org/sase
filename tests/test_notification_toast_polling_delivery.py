"""Tests for ``ace.notification_rules`` applied to the notification poll."""

from __future__ import annotations

import asyncio
import threading
from typing import Any
from unittest.mock import patch

from sase.notifications import delivery

from tests._notification_toasts_helpers import (
    _FakeApp,
    _make,
    _patch_snapshot,
    _plain,
    _use_delivery_rules,
)

_PLAY = "sase.ace.tui.sound_playback.play_sound_file"


def _task_triage(note: str = "Triage this task") -> Any:
    return _make(
        sender="bead",
        action="TaskTriage",
        notes=[note],
        tags=["bead", "task"],
        action_data={"panel": "beads"},
    )


def _axe_error(note: str = "axe crashed") -> Any:
    return _make(sender="axe", action="ViewErrorReport", notes=[note])


def _toast_texts(app: _FakeApp) -> list[str]:
    return [_plain(call.args[0]) for call in app.notify.call_args_list]


def _poll(app: _FakeApp, notifications: list[Any]) -> bool:
    with _patch_snapshot(notifications):
        return asyncio.run(app._poll_agent_completions())


class TestNoRulesKeepsCurrentBehavior:
    """Regression guard: an empty rule list announces exactly as before rules."""

    def test_toast_per_row_and_one_bell(self) -> None:
        app = _FakeApp()
        rows = [
            _make(action="UserQuestion", notes=["first?"]),
            _make(action="UserQuestion", notes=["second?"]),
            _make(action="UserQuestion", notes=["third?"]),
        ]
        with _use_delivery_rules([]), patch(_PLAY) as play:
            _poll(app, rows)

        assert _toast_texts(app) == ["first?", "second?", "third?"]
        assert app._bell_rung == 1
        play.assert_not_called()

    def test_no_rules_never_cross_into_the_core(self) -> None:
        app = _FakeApp()
        with (
            _use_delivery_rules([]),
            patch.object(delivery, "resolve_wire_deliveries") as core,
        ):
            _poll(app, [_make(action="UserQuestion", notes=["q?"])])

        core.assert_not_called()
        assert app._bell_rung == 1


class TestSuppressionByTab:
    _BEADS_RULE = {"name": "quiet-task-beads", "match": {"tab": "beads"}}

    def _rules(self) -> list[dict[str, Any]]:
        return [{**self._BEADS_RULE, "toast": False, "sound": "none"}]

    def test_task_triage_alone_announces_nothing(self) -> None:
        app = _FakeApp()
        with _use_delivery_rules(self._rules()), patch(_PLAY) as play:
            saw_new = _poll(app, [_task_triage()])

        assert saw_new is True
        assert app.notify.call_count == 0
        assert app._bell_rung == 0
        play.assert_not_called()

    def test_axe_row_in_the_same_tick_still_toasts_and_rings(self) -> None:
        app = _FakeApp()
        with _use_delivery_rules(self._rules()), patch(_PLAY) as play:
            _poll(app, [_task_triage(), _axe_error("axe crashed")])

        assert _toast_texts(app) == ["Axe: axe crashed"]
        assert app._bell_rung == 1
        play.assert_not_called()

    def test_suppressed_rows_still_update_indicator_and_snapshot_cache(self) -> None:
        app = _FakeApp()
        triage = _task_triage()
        with _use_delivery_rules(self._rules()):
            _poll(app, [triage])

        assert app.notify.call_count == 0
        assert app._indicator_tab_count("beads") == 1
        assert app._indicator_count == 1
        assert app._last_unread_ids == {triage.id}
        cached: Any = app._notification_snapshot_cache
        assert [n.id for n in cached.notifications] == [triage.id]

    def test_suppressed_rows_are_not_re_announced_on_the_next_tick(self) -> None:
        app = _FakeApp()
        triage = _task_triage()
        axe = _axe_error()
        with _use_delivery_rules(self._rules()):
            _poll(app, [triage])
            _poll(app, [triage, axe])

        assert _toast_texts(app) == ["Axe: axe crashed"]
        assert app._bell_rung == 1


class TestToastBatching:
    def test_six_rows_with_three_suppressed_group_only_the_survivors(self) -> None:
        app = _FakeApp()
        loud = [_make(sender="loud", notes=[f"loud {i}"]) for i in range(3)]
        quiet = [_make(sender="quiet", notes=[f"quiet {i}"]) for i in range(3)]
        rules = [{"match": {"sender": "quiet"}, "toast": False}]
        with _use_delivery_rules(rules):
            # Interleave so suppression cannot rely on the rows being adjacent.
            _poll(app, [quiet[0], loud[0], quiet[1], loud[1], quiet[2], loud[2]])

        # Three survivors stay under the 4+ grouping threshold: one toast each.
        assert _toast_texts(app) == ["loud 0", "loud 1", "loud 2"]

    def test_suppressed_rows_do_not_inflate_a_grouped_toast(self) -> None:
        app = _FakeApp()
        loud = [_make(sender="loud", notes=[f"loud {i}"]) for i in range(4)]
        quiet = [_make(sender="quiet", notes=[f"quiet {i}"]) for i in range(3)]
        rules = [{"match": {"sender": "quiet"}, "toast": False}]
        with _use_delivery_rules(rules):
            _poll(app, [*quiet, *loud])

        texts = _toast_texts(app)
        assert len(texts) == 1
        assert texts[0].startswith("4 ")

    def test_all_rows_suppressed_emits_no_toast(self) -> None:
        app = _FakeApp()
        rows = [_make(notes=[f"row {i}"]) for i in range(5)]
        with _use_delivery_rules([{"toast": False}]):
            _poll(app, rows)

        assert app.notify.call_count == 0
        # The toast axis is independent: the default bell still rings.
        assert app._bell_rung == 1


class TestSoundResolution:
    def test_file_sound_replaces_the_bell(self) -> None:
        app = _FakeApp()
        rules = [{"name": "mac-chime", "sound": "/sounds/glass.aiff"}]
        with _use_delivery_rules(rules), patch(_PLAY) as play:
            _poll(app, [_make(action="UserQuestion", notes=["q?"])])

        assert app._bell_rung == 0
        play.assert_called_once_with("/sounds/glass.aiff")
        assert app.notify.call_count == 1

    def test_mixed_sounds_in_one_tick_play_exactly_one(self) -> None:
        app = _FakeApp()
        rows = [
            _make(sender="a", notes=["from a"]),
            _make(sender="b", notes=["from b"]),
            _make(sender="c", notes=["from c"]),
        ]
        rules = [
            {"match": {"sender": "a"}, "sound": "/sounds/a.wav"},
            {"match": {"sender": "b"}, "sound": "/sounds/b.wav"},
            {"match": {"sender": "c"}, "sound": "bell"},
        ]
        with _use_delivery_rules(rules), patch(_PLAY) as play:
            _poll(app, rows)

        play.assert_called_once_with("/sounds/a.wav")
        assert app._bell_rung == 0

    def test_silent_rows_are_skipped_when_choosing_the_tick_sound(self) -> None:
        app = _FakeApp()
        rows = [
            _make(sender="a", notes=["quiet"]),
            _make(sender="b", notes=["chimes"]),
        ]
        rules = [
            {"match": {"sender": "a"}, "sound": "none"},
            {"match": {"sender": "b"}, "sound": "/sounds/b.wav"},
        ]
        with _use_delivery_rules(rules), patch(_PLAY) as play:
            _poll(app, rows)

        play.assert_called_once_with("/sounds/b.wav")
        assert app._bell_rung == 0

    def test_tick_is_silent_when_every_row_resolves_to_none(self) -> None:
        app = _FakeApp()
        rows = [_make(notes=["one"]), _make(notes=["two"])]
        with _use_delivery_rules([{"sound": "none"}]), patch(_PLAY) as play:
            _poll(app, rows)

        assert app._bell_rung == 0
        play.assert_not_called()
        # The sound axis is independent: both rows still toast.
        assert _toast_texts(app) == ["one", "two"]

    def test_bell_rule_dispatches_to_the_tmux_leaf(self) -> None:
        app = _FakeApp()
        with _use_delivery_rules([{"sound": "bell"}]), patch(_PLAY) as play:
            _poll(app, [_make(notes=["ring"])])

        assert app._bell_rung == 1
        play.assert_not_called()

    def test_row_dismissed_by_plan_reconciliation_does_not_pick_the_sound(
        self,
    ) -> None:
        app = _FakeApp()
        handled = _make(
            sender="plans",
            action="PlanApproval",
            notes=["Plan ready for review: handled.md"],
        )
        other = _make(sender="other", notes=["still live"])
        app._auto_dismissed_notification_ids = {handled.id}
        rules = [{"match": {"sender": "plans"}, "sound": "/sounds/plans.wav"}]
        with _use_delivery_rules(rules), patch(_PLAY) as play:
            _poll(app, [handled, other])

        play.assert_not_called()
        assert app._bell_rung == 1
        assert _toast_texts(app) == ["still live"]

    def test_unplayable_sound_file_never_breaks_the_tick(self) -> None:
        app = _FakeApp()
        rules = [{"sound": "/sounds/missing.wav"}]
        with _use_delivery_rules(rules), patch(_PLAY, return_value=False) as play:
            saw_new = _poll(app, [_make(action="UserQuestion", notes=["q?"])])

        assert saw_new is True
        play.assert_called_once()
        assert app.notify.call_count == 1


class TestResolutionRunsOffTheEventLoop:
    def test_rules_are_resolved_on_the_worker_hop(self) -> None:
        app = _FakeApp()
        loop_thread: list[threading.Thread] = []
        resolver_thread: list[threading.Thread] = []
        real_resolve = delivery.resolve_notification_deliveries

        def _capture(notifications: Any) -> Any:
            resolver_thread.append(threading.current_thread())
            return real_resolve(notifications)

        async def _run() -> None:
            loop_thread.append(threading.current_thread())
            await app._poll_agent_completions()

        with (
            _use_delivery_rules([{"toast": False}]),
            patch.object(delivery, "resolve_notification_deliveries", _capture),
            _patch_snapshot([_make(notes=["x"])]),
        ):
            asyncio.run(_run())

        assert len(resolver_thread) == 1, "the batch resolves in one call"
        assert resolver_thread[0] is not loop_thread[0]

    def test_a_failing_resolver_announces_normally(self) -> None:
        app = _FakeApp()

        def _boom(*_args: Any) -> Any:
            raise RuntimeError("core unavailable")

        with (
            patch.object(delivery, "resolve_notification_deliveries", _boom),
            _patch_snapshot([_make(notes=["still announced"])]),
        ):
            saw_new = asyncio.run(app._poll_agent_completions())

        assert saw_new is True
        assert _toast_texts(app) == ["still announced"]
        assert app._bell_rung == 1
