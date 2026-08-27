"""Ctrl+O / Ctrl+Shift+O prefer the link trail before the old stacks (sase-ug.8)."""

from __future__ import annotations

from sase.ace.tui.actions.navigation._entry_jump_dispatch import EntryJumpDispatchMixin


class _PoisonedTab:
    """Raises if the old jump-history path reads ``current_tab``.

    Proves the link-trail short-circuit returns before touching any of the
    per-surface anchor-stack machinery below it.
    """

    def __get__(self, obj: object, objtype: type | None = None) -> str:
        raise AssertionError("old jump-history path ran despite a pending link trail")


class _TrailFirstApp(EntryJumpDispatchMixin):
    current_tab = _PoisonedTab()

    def __init__(self, *, back: bool, forward: bool) -> None:
        self._back_result = back
        self._forward_result = forward
        self.back_calls = 0
        self.forward_calls = 0

    def _walk_link_trail_back(self) -> bool:
        self.back_calls += 1
        return self._back_result

    def _walk_link_trail_forward(self) -> bool:
        self.forward_calls += 1
        return self._forward_result


class _FallthroughApp(EntryJumpDispatchMixin):
    def __init__(self) -> None:
        self.current_tab = "axe"
        self.current_idx = 1
        self._axe_items = [object(), object()]
        self._entry_jump_mode_active = False
        self._entry_jump_hint_to_index: dict[str, int] = {}
        self._entry_jump_index_to_hint: dict[int, str] = {}
        self._entry_jump_hint_to_target: dict[str, object] = {}
        self._entry_jump_pending_prefix = ""
        self._entry_jump_index_stack: dict[str, list[object]] = {}
        self._entry_jump_forward_index_stack: dict[str, list[object]] = {}
        self._current_patch_group_key = None
        self.refreshed = 0

    def _refresh_current_tab(self) -> None:
        self.refreshed += 1


def test_fast_jump_prefers_a_successful_link_trail_back() -> None:
    app = _TrailFirstApp(back=True, forward=False)

    app.action_jump_to_entry_fast()

    assert app.back_calls == 1


def test_forward_jump_prefers_a_successful_link_trail_forward() -> None:
    app = _TrailFirstApp(back=False, forward=True)

    app.action_jump_to_entry_forward()

    assert app.forward_calls == 1


def test_fast_jump_falls_through_when_the_link_trail_declines() -> None:
    app = _FallthroughApp()

    app.action_jump_to_entry_fast()

    # The old jump-history path resolved the first candidate (index 0),
    # moved there from index 1, and pushed the origin it left behind.
    assert app._entry_jump_mode_active is False
    assert app.current_idx == 0
    assert app._entry_jump_index_stack.get("axe") == [1]


def test_forward_jump_falls_through_when_the_link_trail_declines() -> None:
    app = _FallthroughApp()
    app._entry_jump_forward_index_stack["axe"] = [0]
    app.current_idx = 1

    app.action_jump_to_entry_forward()

    # No ``_walk_link_trail_forward`` on this harness, so the old
    # non-Agents forward-stack path below must have restored the anchor.
    assert app.current_idx == 0
    assert app.refreshed == 1
