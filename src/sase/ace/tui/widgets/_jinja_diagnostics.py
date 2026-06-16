"""Live Jinja2 diagnostics for ``PromptTextArea``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.xprompt import jinja_inspect

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

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._jinja_diagnostics_generation = 0
        self._jinja_diagnostics_timer: Any | None = None
        self._jinja_diagnostics = jinja_inspect.JinjaDiagnostics(
            has_jinja=False,
            ok=True,
        )

    def _on_prompt_completion_context_changed(self) -> None:
        super_changed = getattr(super(), "_on_prompt_completion_context_changed", None)
        if callable(super_changed):
            super_changed()
        self._refresh_jinja_matching_delimiters()
        self._schedule_jinja_diagnostics_refresh()

    def _schedule_jinja_diagnostics_refresh(self) -> None:
        self._jinja_diagnostics_generation += 1
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
        if generation != self._jinja_diagnostics_generation:
            return
        if text != self.text or cursor_offset != self._absolute_offset(
            self.cursor_location
        ):
            return

        diagnostics = jinja_inspect.inspect_template(text)
        self._apply_jinja_diagnostics(diagnostics)

    def _apply_jinja_diagnostics(
        self,
        diagnostics: jinja_inspect.JinjaDiagnostics,
    ) -> None:
        self._jinja_diagnostics = diagnostics
        self._jinja_error_span = diagnostics.span if not diagnostics.ok else None
        unknowns = set(diagnostics.unknown_variables)
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
        if diagnostics.ok and not diagnostics.unknown_variables:
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
        if diagnostics.unknown_variables:
            return f"[bold {theme.warning}]⟨jinja ! var⟩[/]"
        return f"[bold {theme.success}]⟨jinja ✓⟩[/]"

    def _refresh_jinja_matching_delimiters(self) -> None:
        cursor_offset = self._absolute_offset(self.cursor_location)
        spans = jinja_inspect.matching_delimiter_spans(self.text, cursor_offset)
        if spans == self._jinja_matching_delimiter_spans:
            return
        self._jinja_matching_delimiter_spans = spans
        self._refresh_jinja_overlay()
