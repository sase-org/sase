"""Dispatch target selection and source preview for ``PromptInputBar``."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.widgets import Static

from sase.ace.tui.modals.dispatch_target_modal import (
    DispatchTargetChoice,
    DispatchTargetPickerModal,
    LOCAL_DISPATCH_TARGET_ID,
)
from sase.xprompt._directive_scan import scan_dispatch_directive, set_dispatch_directive
from sase.xprompt._exceptions import DirectiveError

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase

    from sase.ace.tui.widgets.prompt_stack import PromptStackState
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
else:
    _MixinBase = object


_DispatchSeverity = str


@dataclass(frozen=True, slots=True)
class _DispatchPickerFocusOwner:
    """Prompt pane that opened the launch-target picker."""

    text_area: Any
    vim_mode: str
    cursor: tuple[int, int]


class PromptInputBarDispatchMixin(_MixinBase):
    """Prompt-local dispatch target UI and pre-submit validation."""

    if TYPE_CHECKING:
        _dispatch_context_line_count: int
        _dispatch_context_visible: bool
        _dispatch_catalog_loaded: bool
        _dispatch_catalog_loading: bool
        _dispatch_target_rows: dict[str, dict[str, object]]
        _dispatch_preflight_override: tuple[str, _DispatchSeverity, str] | None
        _mode: str
        _stack: PromptStackState

        def _cursor_to_end(self, text_area: PromptTextArea) -> None: ...
        def _refocus_prepared_origin(self, prepared: object) -> None: ...
        def _schedule_height_update(self) -> None: ...
        def _sync_state_from_widgets(self) -> None: ...
        def active_text_area(self) -> PromptTextArea: ...

    def _warm_dispatch_target_catalog(self) -> None:
        """Load the local dispatch target catalog off the event loop."""
        if self._mode != "prompt" or self._dispatch_catalog_loading:
            return
        self._dispatch_catalog_loading = True

        def _load() -> None:
            try:
                from sase.dispatch.machine_catalog import (
                    machine_completion_catalog_payload,
                )

                payload = machine_completion_catalog_payload()
                entries = payload.get("entries") if isinstance(payload, Mapping) else ()
                rows = tuple(
                    item for item in entries or () if isinstance(item, Mapping)
                )
                self.app.call_from_thread(
                    self._apply_dispatch_target_catalog,
                    rows,
                    None,
                )
            except Exception as exc:
                self.app.call_from_thread(
                    self._apply_dispatch_target_catalog,
                    (),
                    str(exc),
                )

        try:
            self.run_worker(
                _load,
                name="dispatch-target-catalog",
                thread=True,
                exclusive=True,
                group="dispatch-target-catalog",
            )
        except Exception as exc:
            self._apply_dispatch_target_catalog((), str(exc))

    def _apply_dispatch_target_catalog(
        self,
        rows: tuple[Mapping[str, object], ...],
        error: str | None,
    ) -> None:
        """Apply cached local target rows loaded by the background worker."""
        self._dispatch_catalog_loading = False
        self._dispatch_catalog_loaded = True
        self._dispatch_target_rows = {
            alias: dict(row)
            for row in rows
            if isinstance(alias := row.get("alias"), str) and alias
        }
        if error:
            self._dispatch_preflight_override = (
                f"target catalog unavailable: {error}",
                "warning",
                "",
            )
        self._refresh_dispatch_context_line()

    def request_dispatch_target_picker(self) -> None:
        """Open the prompt-local launch target picker."""
        if self._mode != "prompt" or getattr(
            self._stack.selected_item, "is_auxiliary_pane", False
        ):
            return
        self._sync_state_from_widgets()
        choices = self._dispatch_target_choices()
        current_alias = self._current_dispatch_target_alias()
        owner = self._capture_dispatch_picker_focus_owner()

        def _on_result(option_id: str | None) -> None:
            if option_id is not None:
                alias = None if option_id == LOCAL_DISPATCH_TARGET_ID else option_id
                self._apply_dispatch_target(alias)
            self._restore_dispatch_picker_focus(owner, restore_cursor=option_id is None)

        self.app.push_screen(
            DispatchTargetPickerModal(choices, current_alias=current_alias),
            _on_result,
        )

    def _capture_dispatch_picker_focus_owner(self) -> _DispatchPickerFocusOwner | None:
        """Record the prompt pane that owns keys around the target picker."""
        try:
            text_area = self.active_text_area()
            cursor = text_area.cursor_location
        except Exception:
            return None
        if not isinstance(cursor, tuple) or len(cursor) != 2:
            cursor = (0, 0)
        return _DispatchPickerFocusOwner(
            text_area=text_area,
            vim_mode=str(getattr(text_area, "_vim_mode", "insert") or "insert"),
            cursor=(int(cursor[0]), int(cursor[1])),
        )

    def _restore_dispatch_picker_focus(
        self,
        owner: _DispatchPickerFocusOwner | None,
        *,
        restore_cursor: bool,
    ) -> None:
        """Return Enter ownership to the prompt after picker select or cancel."""

        def _restore() -> None:
            try:
                text_area = owner.text_area if owner is not None else None
                if text_area is None or not getattr(text_area, "is_mounted", False):
                    text_area = self.active_text_area()
                text_area.focus()
                if owner is None:
                    return
                if owner.vim_mode == "insert":
                    text_area._enter_insert_mode()
                else:
                    text_area._enter_normal_mode()
                if restore_cursor:
                    text_area.cursor_location = owner.cursor
            except Exception:
                return

        self.call_after_refresh(_restore)  # type: ignore[attr-defined]

    def _dispatch_target_choices(self) -> tuple[DispatchTargetChoice, ...]:
        choices: list[DispatchTargetChoice] = [
            DispatchTargetChoice(None, "here", "here", "local launch"),
        ]
        for alias, row in sorted(self._dispatch_target_rows.items()):
            status = str(row.get("status") or "unknown")
            detail = str(row.get("documentation") or row.get("endpoint") or "")
            choices.append(
                DispatchTargetChoice(
                    alias,
                    alias,
                    status,
                    detail,
                    enabled=status == "ok",
                )
            )
        return tuple(choices)

    def _current_dispatch_target_alias(self) -> str | None:
        try:
            scan = scan_dispatch_directive(self.active_text_area().text)
        except DirectiveError:
            return None
        return scan.target if scan is not None else None

    def _apply_dispatch_target(self, alias: str | None) -> None:
        try:
            text_area = self.active_text_area()
            text_area.text = set_dispatch_directive(text_area.text, alias)
        except DirectiveError as exc:
            self.notify(str(exc), severity="error")
            return
        except Exception:
            return
        self._dispatch_preflight_override = None
        self._cursor_to_end(text_area)
        text_area.focus()
        self._sync_state_from_widgets()
        self._refresh_dispatch_context_line()
        self._schedule_height_update()

    def _maybe_preflight_dispatch_submission(self, prepared: object) -> bool:
        """Keep directive syntax errors in the editable prompt bar.

        Source validation deliberately happens after ``Submitted`` is posted,
        from the app's pending-launch pipeline.  It can require remote work and
        must not keep an accepted prompt mounted while it runs.
        """
        value = getattr(prepared, "value", "")
        if not isinstance(value, str):
            return False
        try:
            scan_dispatch_directive(value)
        except DirectiveError as exc:
            self._set_dispatch_preflight_override(value, str(exc), "error")
            self.notify(f"Dispatch not submitted: {exc}", severity="error")
            self._refocus_prepared_origin(prepared)
            return True
        return False

    def _set_dispatch_preflight_override(
        self,
        prompt: str,
        message: str,
        severity: _DispatchSeverity,
    ) -> None:
        self._dispatch_preflight_override = (message, severity, prompt)
        self._refresh_dispatch_context_line()

    def _refresh_dispatch_context_line(self) -> None:
        """Render the target/source context line for `%dispatch` prompts."""
        if self._mode != "prompt":
            self._hide_dispatch_context_line()
            return
        try:
            panel = self.query_one("#prompt-dispatch-context", Static)
            text_area = self.active_text_area()
        except Exception:
            return
        text, severity, visible = self._dispatch_context_text(text_area.text)
        if not visible:
            self._hide_dispatch_context_line()
            return
        panel.update(text)
        panel.remove_class("hidden")
        panel.set_class(severity == "error", "error")
        panel.set_class(severity == "warning", "warning")
        panel.set_class(severity == "pending", "pending")
        self._dispatch_context_visible = True
        self._dispatch_context_line_count = 1
        self._schedule_height_update()

    def _hide_dispatch_context_line(self) -> None:
        try:
            panel = self.query_one("#prompt-dispatch-context", Static)
        except Exception:
            return
        panel.update("")
        panel.add_class("hidden")
        panel.set_class(False, "error")
        panel.set_class(False, "warning")
        panel.set_class(False, "pending")
        self._dispatch_context_visible = False
        self._dispatch_context_line_count = 0

    def _dispatch_context_text(
        self,
        prompt: str,
    ) -> tuple[Text, _DispatchSeverity, bool]:
        text = Text()
        severity: _DispatchSeverity = "ok"
        try:
            scan = scan_dispatch_directive(prompt)
        except DirectiveError as exc:
            text.append("Target ", style="bold #87D7FF")
            text.append("error", style="bold #FF5F5F")
            text.append("  ")
            text.append(str(exc), style="#FFAF5F")
            return text, "error", True

        if scan is None:
            return Text(), "ok", False

        target = "here"
        target_status = "local"
        target_style = "bold #87D75F"
        if scan is not None:
            target = scan.target
            row = self._dispatch_target_rows.get(target)
            if row is None and self._dispatch_catalog_loaded:
                target_status = "not enrolled"
                target_style = "bold #FF5F5F"
                severity = "error"
            elif row is None:
                target_status = "checking config"
                target_style = "bold #D7AF5F"
                severity = "pending"
            else:
                target_status = str(row.get("status") or "unknown")
                if target_status == "ok":
                    target_style = "bold #5FD7FF"
                elif target_status == "quarantined":
                    target_style = "bold #D7AF5F"
                    severity = "warning"
                else:
                    target_style = "#D7AF5F"
                    severity = "warning"

        source = self._dispatch_source_label()
        text.append("Target ", style="bold #87D7FF")
        text.append(target, style=target_style)
        text.append(f" {target_status}", style="dim")
        text.append("  Source ", style="bold #87D7FF")
        text.append(source, style="#00D7AF")
        override = self._dispatch_preflight_override
        if override is not None and (not override[2] or override[2] == prompt):
            text.append("  ")
            text.append(override[0], style=_override_style(override[1]))
            severity = override[1]
        elif scan is not None:
            text.append("  proof checked on submit", style="dim")
        visible = scan is not None
        return text, severity, visible

    def _dispatch_source_label(self) -> str:
        ctx = getattr(self.app, "_prompt_context", None)
        project_file = getattr(ctx, "project_file", "") if ctx is not None else ""
        if isinstance(project_file, str) and project_file:
            from pathlib import Path

            project = Path(project_file).expanduser().parent.name
            if project:
                return project
        project_name = getattr(ctx, "project_name", "") if ctx is not None else ""
        return str(project_name or "current")


def _override_style(severity: _DispatchSeverity) -> str:
    if severity == "error":
        return "bold #FF5F5F"
    if severity == "warning":
        return "bold #D7AF5F"
    if severity == "pending":
        return "bold #D7AF5F"
    return "bold #87D75F"


__all__ = ["PromptInputBarDispatchMixin"]
