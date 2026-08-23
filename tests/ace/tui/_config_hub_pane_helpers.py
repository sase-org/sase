"""Shared helpers for ConfigHubPane tests."""

from __future__ import annotations

import pytest
from rich.text import Text
from textual.containers import Vertical
from textual.widgets import Input, Static

from sase.ace.tui.modals.config_hub_catalog import config_subtab_description_text
from sase.ace.tui.modals.config_hub_pane import ConfigHubPane


class _HubChild(Static):
    can_focus = True

    def __init__(self, subtab: str) -> None:
        super().__init__(f"hub {subtab}", id=subtab)
        self.subtab = subtab
        self.visibility: list[bool] = []
        self.focus_count = 0

    def on_center_tab_visibility_changed(self, active: bool) -> None:
        self.visibility.append(active)

    def focus_default(self) -> None:
        self.focus_count += 1
        self.focus()


class _BusyHubChild(_HubChild):
    can_focus = True

    def __init__(self, subtab: str) -> None:
        super().__init__(subtab)
        self.deactivate_checks = 0
        self.close_checks = 0

    def can_deactivate(self) -> bool:
        self.deactivate_checks += 1
        return False

    def can_close(self) -> bool:
        self.close_checks += 1
        return False


class _DigitHubChild(_HubChild):
    BINDINGS = [("1", "record_digit(1)", "Record digit")]

    def __init__(self, subtab: str) -> None:
        super().__init__(subtab)
        self.digits: list[int] = []

    def action_record_digit(self, number: int) -> None:
        self.digits.append(number)


class _ForwardingFilter(Input):
    def on_key(self, event: object) -> None:
        from sase.ace.tui.modals.config_hub_keys import handle_config_hub_bracket_key

        handle_config_hub_bracket_key(self, event)  # type: ignore[arg-type]


class _FilterChild(Vertical):
    def __init__(self, subtab: str) -> None:
        super().__init__(id=subtab)
        self.subtab = subtab

    def compose(self):  # type: ignore[no-untyped-def]
        yield _ForwardingFilter(id="hub-filter")

    def focus_default(self) -> None:
        self.query_one(Input).focus()


def _patch_hub_children(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, list[_HubChild]], list[str]]:
    created: dict[str, list[_HubChild]] = {}
    calls: list[str] = []

    def create(_self: ConfigHubPane, subtab: str) -> _HubChild:
        calls.append(subtab)
        pane = _HubChild(subtab)
        created.setdefault(subtab, []).append(pane)
        return pane

    monkeypatch.setattr(ConfigHubPane, "_create_pane", create)
    return created, calls


def _caption_widget(hub: ConfigHubPane) -> Static:
    return hub.query_one("#config-hub-tab-description", Static)


def _caption_text(hub: ConfigHubPane) -> Text:
    content = _caption_widget(hub).content
    assert isinstance(content, Text)
    return content


def _assert_hub_caption(hub: ConfigHubPane, subtab: str | None = None) -> None:
    active = hub._active_subtab if subtab is None else subtab
    caption = _caption_widget(hub)
    expected = config_subtab_description_text(
        hub._subtab_by_id[active],
        width=int(caption.size.width),
    )
    content = _caption_text(hub)
    assert content.plain == expected.plain
    assert str(content.style) == str(expected.style)
    assert caption.can_focus is False
