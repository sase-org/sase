"""Jump-panel prefix narrowing, subtitles, and toggle availability."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui._app_action_availability import check_app_action
from sase.ace.tui.actions.navigation._member_jump import MemberJumpNavigationMixin
from sase.ace.tui.widgets.agent_detail import AgentDetail
from tests.ace.tui.widgets._agent_jump_panel_helpers import (
    _DetailApp,
    _jump_panel,
    _jump_text,
    _labeled_map,
    _labeled_map_and_roster,
    _show_agent,
    _solo,
)


async def test_two_digit_prefix_narrows_and_restores() -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        jump_map = _labeled_map(_solo(), [f"target-{index:02d}" for index in range(12)])
        assert jump_map.targets[0].number == "00"
        detail._on_member_jump_map(jump_map)  # noqa: SLF001
        await pilot.pause()
        panel = _jump_panel(detail)
        assert not panel.has_class("hidden")
        assert len(_jump_text(panel).splitlines()) <= 2

        detail.set_jump_panel_prefix("1")
        await pilot.pause()
        assert "1▁" in str(panel.border_title)
        assert str(panel.border_subtitle) == "esc cancel"
        narrowed = _jump_text(panel)
        assert "target-10" in narrowed and "target-11" in narrowed
        assert "target-00" not in narrowed

        detail.set_jump_panel_prefix(None)
        await pilot.pause()
        assert "ROSTER" in str(panel.border_title)
        assert "00–11" in str(panel.border_title)
        assert "more" in str(panel.border_subtitle)
        assert "target-00" in _jump_text(panel)


async def test_neighbors_map_shows_dismissed_revive_cells() -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        jump_map, roster = _labeled_map_and_roster(
            _solo(),
            ["lane.peer", "lane.old"],
            roles=["neighbor", "dismissed"],
            title="NEIGHBORS",
            accent="#00D7AF",
        )
        assert roster is not None
        detail._on_member_jump_map(jump_map, roster)  # noqa: SLF001
        await pilot.pause()
        panel = _jump_panel(detail)
        assert not panel.has_class("hidden")
        assert "NEIGHBORS" in str(panel.border_title)
        collapsed = _jump_text(panel)
        assert "lane.peer" in collapsed
        assert "⊘" in collapsed
        assert detail.toggle_jump_panel_expanded() is True
        await pilot.pause()
        expanded = _jump_text(panel)
        assert "❖ NEIGHBORS" in expanded
        assert "⊘" in expanded
        assert "dismissed" in expanded
        detail.set_jump_panel_prefix("1")
        await pilot.pause()
        assert "revive" in _jump_text(panel)
        detail.set_jump_panel_prefix(None)
        await pilot.pause()
        assert "❖ NEIGHBORS" in _jump_text(panel)


async def test_narrow_prefix_without_targets_shows_empty_line() -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        detail._on_member_jump_map(_labeled_map(_solo(), ["aa", "bb"]))  # noqa: SLF001
        await pilot.pause()
        detail.set_jump_panel_prefix("9")
        await pilot.pause()
        assert "no targets start with 9" in _jump_text(_jump_panel(detail))


async def test_unbound_toggle_key_omits_subtitle() -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        panel = _jump_panel(detail)
        detail._on_member_jump_map(_labeled_map(_solo(), ["aa"]))  # noqa: SLF001
        await pilot.pause()
        assert "more" in str(panel.border_subtitle)

        app._keymap_registry = SimpleNamespace(  # noqa: SLF001
            app=SimpleNamespace(toggle_agent_jump_panel="")
        )
        panel._last_digest = None  # noqa: SLF001
        detail._on_member_jump_map(_labeled_map(_solo(), ["aa"]))  # noqa: SLF001
        await pilot.pause()
        assert str(panel.border_subtitle) == ""


def _fallback(_action: str, _parameters: tuple[object, ...]) -> bool:
    return True


class _FakeAgentsApp:
    current_tab = "agents"
    _screen_stack = ("screen",)

    def __init__(self, *, prompt_active: bool, detail: Any) -> None:
        self._prompt_active = prompt_active
        self._detail = detail

    def _prompt_input_active(self) -> bool:
        return self._prompt_active

    def query_one(self, _selector: str, _type: Any = None) -> Any:
        return self._detail


class _FakeDetail:
    def __init__(self, *, available: bool) -> None:
        self._available = available

    def jump_panel_toggle_available(self) -> bool:
        return self._available


def test_toggle_unavailable_while_prompt_input_owns_keys_or_hidden() -> None:
    available = _FakeAgentsApp(prompt_active=False, detail=_FakeDetail(available=True))
    assert check_app_action(available, "toggle_agent_jump_panel", (), _fallback) is True
    busy = _FakeAgentsApp(prompt_active=True, detail=_FakeDetail(available=True))
    assert check_app_action(busy, "toggle_agent_jump_panel", (), _fallback) is False
    hidden = _FakeAgentsApp(prompt_active=False, detail=_FakeDetail(available=False))
    assert check_app_action(hidden, "toggle_agent_jump_panel", (), _fallback) is False


class _RecordingDetail:
    def __init__(self, prefixes: list[str | None]) -> None:
        self._prefixes = prefixes

    def set_jump_panel_prefix(self, prefix: str | None) -> None:
        self._prefixes.append(prefix)


class _PrefixNavStub(MemberJumpNavigationMixin):
    """Minimal host for the pending-digit jump-panel hooks."""

    current_tab = "agents"

    def __init__(self) -> None:
        self._member_jump_pending_digit: str | None = None
        self._member_jump_pending_container_identity: Any = None
        self.prefixes: list[str | None] = []
        self.footer_digits: list[str] = []
        self.footer_refreshes = 0

    def query_one(self, selector: str, _type: Any = None) -> Any:
        if selector == "#agent-detail-panel":
            return _RecordingDetail(self.prefixes)
        return SimpleNamespace(
            update_member_jump_bindings=lambda *args, **_kwargs: (
                self.footer_digits.append(args[0])
            )
        )

    def _refresh_agent_footer_bindings_only(self) -> None:
        self.footer_refreshes += 1


def test_first_digit_hook_narrows_and_cancel_restores() -> None:
    stub = _PrefixNavStub()
    stub._update_member_jump_footer("1")
    assert stub.prefixes == ["1"]

    stub._member_jump_pending_digit = "1"
    assert stub._cancel_member_jump_pending() is True
    assert stub.prefixes == ["1", None]
    assert stub.footer_refreshes == 1

    stub._member_jump_pending_digit = "2"
    stub._update_member_jump_footer("2")
    assert stub._cancel_member_jump_pending(refresh_footer=False) is True
    assert stub.prefixes == ["1", None, "2", None]
    assert stub.footer_refreshes == 1

    assert stub._cancel_member_jump_pending() is False
    assert stub.prefixes == ["1", None, "2", None]
