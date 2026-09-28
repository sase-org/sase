"""Availability of tab switching while a prompt input bar owns keys."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sase.ace.tui._app_action_availability import check_app_action


def _fallback(_action: str, _parameters: tuple[object, ...]) -> bool:
    return True


@dataclass
class _FakeTabApp:
    current_tab: str = "agents"
    _prompt_active: bool = False
    _selected_agent: Any = None
    current_artifacts_pane_key: str = "patches"
    focused: Any = None
    screen: Any = None

    def __post_init__(self) -> None:
        if self.focused is None:
            self.focused = object()
        if self.screen is None:
            self.screen = object()

    def _get_selected_agent(self) -> Any:
        return self._selected_agent

    def _prompt_input_active(self) -> bool:
        return self._prompt_active


def _check(app: _FakeTabApp, action: str) -> bool | None:
    return check_app_action(app, action, (), _fallback)


def test_next_and_prev_tab_unavailable_while_prompt_owns_keys() -> None:
    app = _FakeTabApp(current_tab="agents", _prompt_active=True)

    assert _check(app, "next_tab") is False
    assert _check(app, "prev_tab") is False


def test_next_and_prev_tab_available_without_prompt() -> None:
    app = _FakeTabApp(current_tab="agents", _prompt_active=False)

    assert _check(app, "next_tab") is True
    assert _check(app, "prev_tab") is True


def test_restore_quit_unavailable_while_prompt_owns_keys() -> None:
    """`@`/`q`/`Q` never fire a global action while a prompt owns keys."""
    app = _FakeTabApp(current_tab="agents", _prompt_active=True)

    assert _check(app, "restore_prompt_stash") is False
    assert _check(app, "quit") is False
    assert _check(app, "stop_axe_and_quit") is False


def test_restore_quit_available_without_prompt() -> None:
    app = _FakeTabApp(current_tab="agents", _prompt_active=False)

    assert _check(app, "restore_prompt_stash") is True
    assert _check(app, "quit") is True
    assert _check(app, "stop_axe_and_quit") is True
