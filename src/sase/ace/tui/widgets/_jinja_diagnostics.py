"""Live Jinja2 diagnostics for ``PromptTextArea``."""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any

from sase.ace.tui.util.pump_tasks import cancel_pump_free_tasks, spawn_pump_free_task
from sase.ace.tui.widgets.jinja_completion import jinja_scope_for_editor
from sase.macro import jinja_assist, jinja_inspect

_POSITIONAL_RE = re.compile(r"_[0-9]+")

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


class JinjaDiagnosticsMixin(_MixinBase):
    """Debounced prompt-template diagnostics and chip state."""

    if TYPE_CHECKING:
        _jinja_error_span: tuple[int, int] | None
        _jinja_matching_delimiter_spans: tuple[tuple[int, int], ...]
        _jinja_unknown_spans: tuple[tuple[int, int], ...]

        def _find_prompt_bar(self) -> Any: ...
        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _prompt_completion_settings(self) -> Any: ...
        def _refresh_jinja_overlay(self) -> None: ...

        is_mounted: bool

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._jinja_diagnostics_generation = 0
        self._jinja_diagnostics_timer: Any | None = None
        self._jinja_diagnostics_task: Any | None = None
        self._jinja_diagnostics = jinja_inspect.JinjaDiagnostics(
            has_jinja=False,
            ok=True,
        )

    def _prompt_unmount_hook(self) -> None:
        """Stop the diagnostics timer and drop any in-flight inspect task."""
        if self._jinja_diagnostics_timer is not None:
            self._jinja_diagnostics_timer.stop()
            self._jinja_diagnostics_timer = None
        self._jinja_diagnostics_generation += 1
        self._cancel_jinja_diagnostics_task()
        cancel_pump_free_tasks(self)
        super_hook = getattr(super(), "_prompt_unmount_hook", None)
        if callable(super_hook):
            super_hook()

    def _on_prompt_completion_context_changed(self) -> None:
        super_changed = getattr(super(), "_on_prompt_completion_context_changed", None)
        if callable(super_changed):
            super_changed()
        self._refresh_jinja_matching_delimiters()
        self._schedule_jinja_diagnostics_refresh()

    def _schedule_jinja_diagnostics_refresh(self) -> None:
        self._jinja_diagnostics_generation += 1
        self._cancel_jinja_diagnostics_task()
        if self._jinja_diagnostics_timer is not None:
            self._jinja_diagnostics_timer.stop()
        settings_getter = getattr(self, "_prompt_completion_settings", None)
        debounce_ms = 90
        if callable(settings_getter):
            debounce_ms = int(getattr(settings_getter(), "debounce_ms", debounce_ms))
        generation = self._jinja_diagnostics_generation
        text = self.text
        cursor_offset = self._absolute_offset(self.cursor_location)
        self._jinja_diagnostics_timer = self.set_timer(
            debounce_ms / 1000,
            lambda: self._fire_jinja_diagnostics_timer(
                generation,
                text,
                cursor_offset,
            ),
        )

    def _fire_jinja_diagnostics_timer(
        self,
        generation: int,
        text: str,
        cursor_offset: int,
    ) -> None:
        self._jinja_diagnostics_timer = None
        if not self.is_mounted:
            return
        if generation != self._jinja_diagnostics_generation:
            return
        if text != self.text or cursor_offset != self._absolute_offset(
            self.cursor_location
        ):
            return

        # The engine scope is an immutable snapshot captured on the pump;
        # the inspect itself runs in a pump-free thread task.
        scope = jinja_scope_for_editor(self)
        task = spawn_pump_free_task(
            self,
            self._run_jinja_diagnostics_async(generation, text, cursor_offset, scope),
            name="jinja-diagnostics",
            registry_attr="_jinja_diagnostics_async_tasks",
        )
        self._jinja_diagnostics_task = task
        if task is None:
            self._apply_jinja_diagnostics(_inspect_with_scope(scope, text))

    async def _run_jinja_diagnostics_async(
        self,
        generation: int,
        text: str,
        cursor_offset: int,
        scope: jinja_assist.JinjaScope,
    ) -> None:
        """Inspect *text* off the pump and apply it when still current."""
        try:
            diagnostics = await asyncio.to_thread(_inspect_with_scope, scope, text)
        finally:
            current = asyncio.current_task()
            if current is not None and self._jinja_diagnostics_task is current:
                self._jinja_diagnostics_task = None
        if generation != self._jinja_diagnostics_generation:
            return
        if not self.is_mounted:
            return
        if text != self.text or cursor_offset != self._absolute_offset(
            self.cursor_location
        ):
            return
        self._apply_jinja_diagnostics(diagnostics)

    def _cancel_jinja_diagnostics_task(self) -> None:
        task = getattr(self, "_jinja_diagnostics_task", None)
        if task is None:
            return
        self._jinja_diagnostics_task = None
        if not task.done():
            task.cancel()

    def _apply_jinja_diagnostics(
        self,
        diagnostics: jinja_inspect.JinjaDiagnostics,
    ) -> None:
        self._jinja_diagnostics = diagnostics
        self._jinja_error_span = diagnostics.span if not diagnostics.ok else None
        unknowns = set(diagnostics.unknown_variables)
        unknowns.update(
            unavailable.name for unavailable in diagnostics.unavailable_variables
        )
        if unknowns:
            self._jinja_unknown_spans = tuple(
                (span.start, span.end)
                for span in jinja_inspect.tokenize(self.text)
                if span.kind == "variable" and span.value in unknowns
            )
        else:
            self._jinja_unknown_spans = ()
        self._refresh_jinja_overlay()
        self._publish_jinja_diagnostics()

    def _publish_jinja_diagnostics(self) -> None:
        bar = self._find_prompt_bar()
        if bar is None:
            return
        refresh = getattr(bar, "_refresh_title", None)
        if callable(refresh):
            refresh(getattr(bar, "_title_mode_suffix", ""))
        show = getattr(bar, "show_jinja_diagnostics", None)
        hide = getattr(bar, "hide_jinja_diagnostics", None)
        diagnostics = self._jinja_diagnostics
        if not diagnostics.has_jinja:
            if callable(hide):
                hide()
            return
        if (
            diagnostics.ok
            and not diagnostics.unknown_variables
            and not diagnostics.unavailable_variables
        ):
            if callable(hide):
                hide()
            return
        if callable(show):
            show(diagnostics)

    def _jinja_chip_markup(self) -> str:
        diagnostics = self._jinja_diagnostics
        if not diagnostics.has_jinja:
            return ""
        theme = self.app.current_theme
        if not diagnostics.ok:
            line = diagnostics.lineno or 1
            return f"[bold {theme.warning}]⟨jinja ! L{line}⟩[/]"
        if diagnostics.unknown_variables or diagnostics.unavailable_variables:
            return f"[bold {theme.warning}]⟨jinja ! var⟩[/]"
        return f"[bold {theme.success}]⟨jinja ✓⟩[/]"

    def _refresh_jinja_matching_delimiters(self) -> None:
        cursor_offset = self._absolute_offset(self.cursor_location)
        spans = jinja_inspect.matching_delimiter_spans(self.text, cursor_offset)
        if spans == self._jinja_matching_delimiter_spans:
            return
        self._jinja_matching_delimiter_spans = spans
        self._refresh_jinja_overlay()


def _inspect_with_scope(
    scope: jinja_assist.JinjaScope, text: str
) -> jinja_inspect.JinjaDiagnostics:
    """Lint *text* against a snapshot engine *scope*.

    Both inputs are immutable values, so this may run in a worker thread.
    """
    scope_vars: jinja_assist.JinjaScopeVariables = jinja_assist.jinja_scope_variables(
        text, scope
    )
    diagnostics = jinja_inspect.diagnose(text)
    if not diagnostics.has_jinja or not diagnostics.ok:
        return diagnostics
    known = set(scope_vars.known)
    undeclared = set(jinja_inspect.unknown_variables(text, known))
    unavailable_names = {unavailable.name for unavailable in scope_vars.unavailable}
    unknown = sorted(undeclared - unavailable_names)
    if scope_vars.positional_pattern:
        unknown = [name for name in unknown if _POSITIONAL_RE.fullmatch(name) is None]
    unavailable = tuple(
        unavailable
        for unavailable in scope_vars.unavailable
        if unavailable.name in undeclared
    )
    if not unknown and not unavailable:
        return diagnostics
    return jinja_inspect.JinjaDiagnostics(
        has_jinja=diagnostics.has_jinja,
        ok=diagnostics.ok,
        message=diagnostics.message,
        lineno=diagnostics.lineno,
        col=diagnostics.col,
        span=diagnostics.span,
        unknown_variables=tuple(unknown),
        unavailable_variables=unavailable,
    )
