"""Initialization-plan preview modal for the Admin Center Projects tab."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rich.console import RenderableType
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from .confirm_dialog import ButtonVariant, ConfirmKind
from .init_plan_modal_rendering import (
    init_plan_border_subtitle,
    init_plan_confirm_label,
    init_plan_is_danger,
    init_plan_renderable,
    init_plan_title,
    runnable_project_count,
)
from .projects_pane_init import InitScope
from .projects_pane_init_payload import InitCheckPayload

InitPlanAction = Literal["apply"]


@dataclass(frozen=True, slots=True)
class InitPlanDecision:
    """Typed dismissal record. Phase ``valve`` widens ``action`` in place."""

    action: InitPlanAction


class InitPlanModal(ModalScreen[InitPlanDecision | None]):
    """Confirm a project initialization after previewing its exact argv."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("n", "cancel", "Cancel"),
        ("y", "confirm", "Confirm"),
        ("d", "toggle_diffs", "Toggle diffs"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
    ]

    def __init__(self, scope: InitScope, payload: InitCheckPayload) -> None:
        super().__init__()
        self.add_class("confirm-dialog")
        self._scope = scope
        self._payload = payload
        self._show_diffs = False
        self._kind = (
            ConfirmKind.DANGER if init_plan_is_danger(payload) else ConfirmKind.NEUTRAL
        )
        self._runnable = runnable_project_count(payload)
        self._title = init_plan_title(scope, payload)

    def compose(self) -> ComposeResult:
        with Container(
            id="init-plan-container",
            classes=f"confirm-dialog-panel confirm-dialog--{self._kind.value}",
        ) as dialog:
            dialog.border_title = self._build_border_title()
            dialog.border_subtitle = init_plan_border_subtitle(
                show_diffs=self._show_diffs
            )
            with VerticalScroll(id="init-plan-preview-scroll") as preview_scroll:
                preview_scroll.border_title = "Initialization plan"
                yield Static(self._preview_renderable(), id="init-plan-preview")
            with Horizontal(id="init-plan-buttons"):
                confirm = Button(
                    init_plan_confirm_label(self._scope, self._payload),
                    id="init-plan-confirm",
                    variant=self._confirm_button_variant(),
                )
                confirm.disabled = self._runnable == 0
                yield confirm
                yield Button(
                    "Cancel (n)",
                    id="init-plan-cancel",
                    variant=self._cancel_button_variant(),
                )

    def on_mount(self) -> None:
        self.call_after_refresh(self._sync_preview_scroll_hint)

    def on_resize(self, _event: events.Resize) -> None:
        self.call_after_refresh(self._sync_preview_scroll_hint)

    def _preview_renderable(self) -> RenderableType:
        return init_plan_renderable(
            self._scope,
            self._payload,
            show_diffs=self._show_diffs,
        )

    def _build_border_title(self) -> Text:
        title = Text()
        title.append("↻", style=self._title_icon_style())
        title.append("  ")
        title.append(self._title, style="bold")
        return title

    def _title_icon_style(self) -> str:
        return "bold red" if self._kind is ConfirmKind.DANGER else "bold cyan"

    def _confirm_button_variant(self) -> ButtonVariant:
        if self._runnable == 0:
            return "default"
        return "error" if self._kind is ConfirmKind.DANGER else "primary"

    def _cancel_button_variant(self) -> ButtonVariant:
        return "primary" if self._kind is ConfirmKind.DANGER else "default"

    def _sync_preview_scroll_hint(self) -> None:
        scroll = self._preview_scroll()
        if scroll is None:
            return
        has_overflow = int(getattr(scroll, "max_scroll_y", 0)) > 0
        class_is_set = self.has_class("has-scrollable-preview")
        if has_overflow != class_is_set:
            if has_overflow:
                self.add_class("has-scrollable-preview")
            else:
                self.remove_class("has-scrollable-preview")
            self.call_after_refresh(self._sync_preview_scroll_hint)
            return
        scroll.border_subtitle = "ctrl+d/u scroll" if has_overflow else ""

    def _preview_scroll(self) -> VerticalScroll | None:
        if not getattr(self, "is_attached", True):
            return None
        try:
            return self.query_one("#init-plan-preview-scroll", VerticalScroll)
        except Exception:
            return None

    def _refresh_preview(self) -> None:
        try:
            self.query_one("#init-plan-preview", Static).update(
                self._preview_renderable()
            )
        except Exception:
            return
        try:
            self.query_one(
                "#init-plan-container", Container
            ).border_subtitle = init_plan_border_subtitle(show_diffs=self._show_diffs)
        except Exception:
            pass
        scroll = self._preview_scroll()
        if scroll is not None:
            scroll.scroll_to(y=0, animate=False)
        self.call_after_refresh(self._sync_preview_scroll_hint)

    def action_toggle_diffs(self) -> None:
        self._show_diffs = not self._show_diffs
        self._refresh_preview()

    def action_confirm(self) -> None:
        if self._runnable == 0:
            return
        self.dismiss(InitPlanDecision(action="apply"))

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_scroll_down(self) -> None:
        scroll = self._preview_scroll()
        if scroll is None or not self._can_scroll_down(scroll):
            return
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=max(1, height // 2), animate=False)

    def action_scroll_up(self) -> None:
        scroll = self._preview_scroll()
        if scroll is None or not self._can_scroll_up(scroll):
            return
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=-(max(1, height // 2)), animate=False)

    @staticmethod
    def _can_scroll_down(scroll: VerticalScroll) -> bool:
        return float(scroll.scroll_y) < int(getattr(scroll, "max_scroll_y", 0))

    @staticmethod
    def _can_scroll_up(scroll: VerticalScroll) -> bool:
        return float(scroll.scroll_y) > 0

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "init-plan-confirm":
            self.action_confirm()
        else:
            self.action_cancel()


__all__ = ["InitPlanAction", "InitPlanDecision", "InitPlanModal"]
