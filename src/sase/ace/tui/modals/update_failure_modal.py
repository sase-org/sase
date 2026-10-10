"""Failure-report modal for the red updates gear.

Opened by clicking the red gear (or the ``f`` Update-panel row in a later
phase). Reports the journal's recorded failure: what ran, how it failed,
and the tail of its output. ``u`` jumps to the Update panel, ``d``
dismisses the recorded failure, and ``y`` copies the report.
"""

from __future__ import annotations

from typing import Literal

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.ace._update_attempts_model import UpdateFailure
from sase.ace.tui.update_gear import format_failure_when
from sase.ace.tui.widgets.update_accents import UPDATE_FAILED_ACCENT

from ..actions.clipboard import schedule_copy_delivery
from .base import CopyModeForwardingMixin
from .update_failure_geometry import (
    PLACEHOLDER_TEXT,
    SEPARATOR_TEXT,
    UpdateFailureGeometry,
    compute_geometry,
    expand_tabs,
)

UpdateFailureChoice = Literal["dismiss", "open_update"]


class UpdateFailureModal(
    CopyModeForwardingMixin, ModalScreen[UpdateFailureChoice | None]
):
    """Show one recorded update failure with its output tail."""

    BINDINGS = [
        ("u", "open_update", "Open Update"),
        ("d", "dismiss_failure", "Dismiss"),
        ("y", "copy_report", "Copy"),
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
        ("g", "scroll_to_top", "Top"),
        ("G", "scroll_to_bottom", "Bottom"),
    ]

    def __init__(self, failure: UpdateFailure) -> None:
        super().__init__()
        self._failure = failure
        when = format_failure_when(failure.finished_at)
        verb = "interrupted" if failure.interrupted else "failed"
        if failure.interrupted:
            headline = (
                f'ACE exited before "{failure.label}" finished; '
                "the install may be incomplete."
            )
        else:
            headline = failure.error
        self._meta_text = f"{failure.label} · {failure.stage} · {verb} {when}"
        self._headline_text = headline
        self._body_text = (
            failure.output_tail if failure.output_tail else PLACEHOLDER_TEXT
        )
        self._title_text = (
            "✗ Update interrupted" if failure.interrupted else "✗ Update failed"
        )
        self._last_geometry_screen: tuple[int, int] | None = None
        self._applied_geometry: tuple[int, int] | None = None
        self._geometry_cache: dict[tuple[int, int], tuple[int, int, bool]] = {}
        self._settle_corrections = 0

    @property
    def failure(self) -> UpdateFailure:
        """The recorded failure this report covers."""
        return self._failure

    def compose(self) -> ComposeResult:
        with Container(id="update-failure-container"):
            with VerticalScroll(id="update-failure-scroll"):
                yield Static(
                    Text(expand_tabs(self._meta_text), style="dim"),
                    id="update-failure-meta",
                )
                yield Static(
                    Text(
                        expand_tabs(self._headline_text),
                        style=f"bold {UPDATE_FAILED_ACCENT}",
                    ),
                    id="update-failure-error",
                )
                yield Static(
                    Text(expand_tabs(SEPARATOR_TEXT), style="dim"),
                    id="update-failure-output-label",
                )
                yield Static(
                    Text(expand_tabs(self._body_text)),
                    id="update-failure-body",
                )
            yield Static(
                Text("", style="dim"),
                id="update-failure-footer",
            )
            hint = Static(
                Text("", style="dim"),
                id="update-failure-scroll-hint",
            )
            hint.display = False
            yield hint

    def on_mount(self) -> None:
        container = self.query_one("#update-failure-container", Container)
        container.border_title = Text(
            self._title_text, style=f"bold {UPDATE_FAILED_ACCENT}"
        )
        self._apply_adaptive_geometry()
        try:
            self.query_one("#update-failure-scroll", VerticalScroll).focus()
        except Exception:
            pass
        # One bounded settle correction after the first frame, in case the
        # fallback TCSS size differs from the computed rectangle.
        try:
            self.call_after_refresh(self._settle_geometry)
        except Exception:
            pass

    def on_resize(self, _event: events.Resize) -> None:
        """Recompute on real terminal-size changes only."""
        if not self.is_mounted:
            return
        try:
            size = self.app.size
            current = (int(size.width), int(size.height))
        except Exception:
            return
        if current == self._last_geometry_screen:
            # Child layout event caused by applying new dimensions.
            return
        self._apply_adaptive_geometry()

    def _settle_geometry(self) -> None:
        if self._settle_corrections >= 1:
            return
        self._settle_corrections += 1
        before = self._applied_geometry
        self._apply_adaptive_geometry()
        if self._applied_geometry != before:
            # Geometry converged on a second value; do not loop further.
            pass

    def _apply_adaptive_geometry(self) -> None:
        if not self.is_mounted:
            return
        try:
            size = self.app.size
            screen_w, screen_h = int(size.width), int(size.height)
        except Exception:
            return
        if screen_w <= 0 or screen_h <= 0:
            return
        if (
            screen_w,
            screen_h,
        ) == self._last_geometry_screen and self._applied_geometry is not None:
            return
        geometry = compute_geometry(
            screen_w=screen_w,
            screen_h=screen_h,
            meta=self._meta_text,
            headline=self._headline_text,
            body=self._body_text,
            title=self._title_text,
        )
        if geometry is None:
            return
        self._geometry_cache[(screen_w, screen_h)] = (
            geometry.width,
            geometry.height,
            geometry.show_scroll_hint,
        )
        if self._applied_geometry == (geometry.width, geometry.height):
            self._last_geometry_screen = (screen_w, screen_h)
            self._refresh_footer(geometry)
            return
        try:
            scroll = self.query_one("#update-failure-scroll", VerticalScroll)
            was_at_bottom = bool(scroll.is_vertical_scroll_end)
            saved_y = float(scroll.scroll_y)
        except Exception:
            scroll = None
            was_at_bottom = False
            saved_y = 0.0
        try:
            container = self.query_one("#update-failure-container", Container)
        except Exception:
            return
        container.styles.width = geometry.width
        container.styles.height = geometry.height
        container.styles.max_width = None
        container.styles.max_height = None
        if geometry.cramped:
            container.add_class("-cramped")
        else:
            container.remove_class("-cramped")
        self._refresh_footer(geometry)
        self._last_geometry_screen = (screen_w, screen_h)
        self._applied_geometry = (geometry.width, geometry.height)
        if scroll is not None:
            try:
                if was_at_bottom:
                    scroll.scroll_end(animate=False)
                else:
                    max_y = float(scroll.max_scroll_y)
                    scroll.scroll_to(y=max(0.0, min(saved_y, max_y)), animate=False)
            except Exception:
                pass

    def _refresh_footer(self, geometry: UpdateFailureGeometry) -> None:
        try:
            footer = self.query_one("#update-failure-footer", Static)
        except Exception:
            return
        try:
            hint = self.query_one("#update-failure-scroll-hint", Static)
        except Exception:
            hint = None
        action_text = "\n".join(geometry.footer_lines)
        rendered = footer.render()
        current = rendered.plain if isinstance(rendered, Text) else str(rendered)
        if current != action_text:
            footer.update(Text(action_text, style="dim"))
        if hint is not None:
            hint.display = bool(geometry.show_scroll_hint)
            if geometry.show_scroll_hint:
                hint_text = "\n".join(geometry.hint_lines)
                hint_rendered = hint.render()
                hint_current = (
                    hint_rendered.plain
                    if isinstance(hint_rendered, Text)
                    else str(hint_rendered)
                )
                if hint_current != hint_text:
                    hint.update(Text(hint_text, style="dim"))

    def action_open_update(self) -> None:
        self.dismiss("open_update")

    def action_dismiss_failure(self) -> None:
        self.dismiss("dismiss")

    def action_close(self) -> None:
        self.dismiss(None)

    def action_copy_report(self) -> None:
        schedule_copy_delivery(
            self,
            self._copy_text(),
            copied_label="update failure report",
            task_name="sase-copy-update-failure-report",
        )

    def _copy_text(self) -> str:
        parts = [self._failure.error]
        if self._failure.output_tail:
            parts.append(self._failure.output_tail)
        return "\n\n".join(parts)

    def _half_page_step(self) -> int:
        try:
            scroll = self.query_one("#update-failure-scroll", VerticalScroll)
            step = int(scroll.scrollable_content_region.height // 2)
        except Exception:
            step = 0
        return max(1, step)

    def action_scroll_down(self) -> None:
        scroll = self.query_one("#update-failure-scroll", VerticalScroll)
        scroll.scroll_relative(y=self._half_page_step())

    def action_scroll_up(self) -> None:
        scroll = self.query_one("#update-failure-scroll", VerticalScroll)
        scroll.scroll_relative(y=-self._half_page_step())

    def action_scroll_to_top(self) -> None:
        self.query_one("#update-failure-scroll", VerticalScroll).scroll_home(
            animate=False
        )

    def action_scroll_to_bottom(self) -> None:
        self.query_one("#update-failure-scroll", VerticalScroll).scroll_end(
            animate=False
        )


__all__ = ["UpdateFailureChoice", "UpdateFailureModal"]
