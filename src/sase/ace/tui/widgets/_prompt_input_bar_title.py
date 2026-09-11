"""Title and xprompt target chrome for ``PromptInputBar``."""

from __future__ import annotations

from pathlib import Path
import time
from typing import TYPE_CHECKING

from rich.cells import cell_len
from rich.markup import escape

from sase.ace.tui.widgets.prompt_stack import (
    PromptStackState,
    XPromptReadonlyTarget,
)

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase

    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
else:
    _MixinBase = object

_TARGET_STALE_CHECK_INTERVAL_SECONDS = 3.0


def _take_cells(value: str, width: int, *, from_right: bool = False) -> str:
    """Return a prefix/suffix of *value* that fits in *width* terminal cells."""
    if width <= 0:
        return ""
    chars = reversed(value) if from_right else iter(value)
    used = 0
    taken: list[str] = []
    for char in chars:
        char_width = max(cell_len(char), 0)
        if used + char_width > width:
            break
        taken.append(char)
        used += char_width
    if from_right:
        taken.reverse()
    return "".join(taken)


def _middle_elide_cells(value: str, width: int) -> str:
    """Fit *value* in *width* cells, preserving the path tail."""
    if width <= 0:
        return ""
    if cell_len(value) <= width:
        return value
    if width == 1:
        return "…"
    left_width = max(1, (width - 1) // 2)
    right_width = max(0, width - 1 - left_width)
    suffix = _take_cells(value, right_width, from_right=True)
    return f"{_take_cells(value, left_width)}…{suffix}"


class PromptInputBarTitleMixin(_MixinBase):
    """Border title, target-state chip, and target staleness helpers."""

    if TYPE_CHECKING:
        _mode: str
        _readonly_xprompt_target: XPromptReadonlyTarget | None
        _stack: PromptStackState
        _title_mode_suffix: str
        _xprompt_source_stale: bool
        _xprompt_stale_check_in_flight: bool
        _xprompt_stale_checked_mono: float
        _xprompt_target_generation: int

        def _active_jinja_chip_markup(self) -> str: ...
        def _refresh_target_classes(self) -> None: ...
        def _sync_state_from_widgets(self) -> None: ...
        def _todo_chip_markup(self) -> str: ...
        def active_text_area(self) -> PromptTextArea: ...
        def insert_mode_subtitle(self) -> str: ...
        def normal_mode_subtitle(self) -> str: ...
        def refresh_frontmatter_panel_from_stack(self) -> None: ...
        def set_prompt_mode_subtitle(self, subtitle: str) -> None: ...

    @property
    def _base_title(self) -> str:
        """Return the base border title based on mode."""
        if self._mode == "feedback":
            return "Plan Feedback"
        if self._mode == "approve_prompt":
            return "Coder Prompt"
        return "Prompt"

    def _refresh_title(self, mode_suffix: str = "") -> None:
        """Refresh the border title, including stack count in prompt stacks."""
        self._title_mode_suffix = mode_suffix
        title = self._base_title
        if self._mode == "prompt" and self._stack.agent_count > 1:
            title = f"{title} · {self._stack.agent_count} agents"
        if self._mode == "prompt" and (
            self._stack.binding is not None or self._readonly_xprompt_target is not None
        ):
            try:
                self._sync_state_from_widgets()
            except Exception:
                pass
            target = self._target_title_payload()
            if target is not None:
                title = self._format_target_title(title, target)
                self._refresh_target_classes()
        if mode_suffix:
            # Border titles parse Rich markup; escape literal mode brackets.
            mode_suffix = mode_suffix.replace("[", "\\[")
            title = f"{title} {mode_suffix}"
        todo_chip = self._todo_chip_markup()
        if todo_chip:
            title = f"{title}  {todo_chip}"
        chip = self._active_jinja_chip_markup()
        if chip:
            title = f"{title}  {chip}"
        self.border_title = title

    def _target_title_payload(self) -> tuple[str, str | None, str] | None:
        """Return ``(reference, path, state)`` for the target title chrome."""
        readonly = self._readonly_xprompt_target
        if readonly is not None:
            return readonly.reference, readonly.path, "readonly"
        binding = self._stack.binding
        if binding is None:
            return None
        if self._xprompt_source_stale:
            state = "stale"
        elif self._stack.is_dirty:
            state = "dirty"
        else:
            state = "clean"
        return binding.reference, binding.write_path, state

    def _format_target_title(
        self,
        prefix: str,
        target: tuple[str, str | None, str],
    ) -> str:
        reference, path, state = target
        state_plain = {
            "clean": "✓",
            "dirty": "●",
            "readonly": "🔒 read-only",
            "stale": "⚠ changed on disk",
        }[state]
        path_markup = ""
        if path:
            width = self._target_path_width(prefix, reference, state_plain)
            path_markup = f" · [dim]{escape(self._target_display_path(path, width))}[/]"
        return (
            f"{prefix} · {self._target_reference_chip_markup(reference)}"
            f"{path_markup} · {self._target_state_marker_markup(state)}"
        )

    def _target_reference_chip_markup(self, reference: str) -> str:
        theme = self._current_theme()
        foreground = self._theme_color(theme, "background", "black")
        background = self._theme_color(theme, "secondary", "cyan")
        return f"[bold {foreground} on {background}] ✎ {escape(reference)} [/]"

    def _target_state_marker_markup(self, state: str) -> str:
        theme = self._current_theme()
        if state == "clean":
            return "[dim]✓[/]"
        if state == "dirty":
            return f"[bold {self._theme_color(theme, 'warning', 'yellow')}]●[/]"
        if state == "readonly":
            muted = self._theme_color(theme, "foreground", "white")
            return f"[dim {muted}]🔒 read-only[/]"
        warning = self._theme_color(theme, "warning", "yellow")
        return f"[bold {warning}]⚠ changed on disk[/]"

    def _target_path_width(
        self,
        prefix: str,
        reference: str,
        state_plain: str,
    ) -> int:
        try:
            total_width = int(self.size.width)
        except Exception:
            total_width = 0
        if total_width <= 0:
            total_width = 88
        reserved = (
            cell_len(prefix)
            + cell_len(f" · ✎ {reference} ")
            + cell_len(f" · {state_plain}")
            + 10
        )
        return max(12, min(56, total_width - reserved))

    @staticmethod
    def _target_display_path(path: str, width: int) -> str:
        home = str(Path.home())
        collapsed = path
        if path == home:
            collapsed = "~"
        elif path.startswith(home + "/"):
            collapsed = "~" + path[len(home) :]
        return _middle_elide_cells(" ".join(collapsed.splitlines()), width)

    def _current_theme(self) -> object | None:
        try:
            return self.app.current_theme
        except Exception:
            return None

    @staticmethod
    def _theme_color(theme: object | None, attr: str, fallback: str) -> str:
        if theme is not None:
            color = getattr(theme, attr, None)
            if color:
                return str(color)
        return fallback

    def _target_hint_reference(self) -> str | None:
        readonly = self._readonly_xprompt_target
        if readonly is not None:
            return readonly.reference
        binding = self._stack.binding
        return binding.reference if binding is not None else None

    def _target_save_hint(self) -> str:
        reference = self._target_hint_reference()
        if reference is None:
            return ""
        verb = "save as" if self._readonly_xprompt_target is not None else "save"
        return f"  [^G w] {verb} {_middle_elide_cells(reference, 24)}"

    def mark_readonly_xprompt_target(self, target: XPromptReadonlyTarget) -> None:
        """Show a persistent read-only source state without binding writes."""
        self._stack.unbind()
        self._readonly_xprompt_target = target
        self._xprompt_source_stale = False
        self._xprompt_target_generation += 1
        self._refresh_target_classes()
        self._refresh_title()
        self._refresh_prompt_mode_subtitle()
        self.refresh_frontmatter_panel_from_stack()

    def _mark_xprompt_source_fresh(self) -> None:
        """Clear the display-only stale flag after a successful write/reload."""
        self._xprompt_source_stale = False
        self._xprompt_target_generation += 1
        self._refresh_target_classes()

    def _schedule_xprompt_stale_check(self, *, force: bool = False) -> None:
        """Schedule one stat-only source staleness check in a worker thread."""
        binding = self._stack.binding
        if binding is None or self._readonly_xprompt_target is not None:
            return
        if not self.is_mounted:
            return
        now = time.monotonic()
        if (
            not force
            and self._xprompt_stale_checked_mono > 0.0
            and now - self._xprompt_stale_checked_mono
            < _TARGET_STALE_CHECK_INTERVAL_SECONDS
        ):
            return
        if self._xprompt_stale_check_in_flight:
            return
        generation = self._xprompt_target_generation
        write_path = binding.write_path
        fingerprint = binding.loaded_fingerprint
        self._xprompt_stale_check_in_flight = True

        def _check() -> None:
            stale = not fingerprint.matches_stat(write_path)
            completed = time.monotonic()
            try:
                self.app.call_from_thread(
                    self._complete_xprompt_stale_check,
                    generation,
                    write_path,
                    stale,
                    completed,
                )
            except Exception:
                self._xprompt_stale_check_in_flight = False

        try:
            self.run_worker(
                _check,
                name="xprompt-target-stale-check",
                thread=True,
                exclusive=True,
                group="xprompt-target-stale-check",
            )
        except Exception:
            self._xprompt_stale_check_in_flight = False

    def _complete_xprompt_stale_check(
        self,
        generation: int,
        write_path: str,
        stale: bool,
        completed_mono: float,
    ) -> None:
        """Apply a worker staleness result if it still matches this target."""
        self._xprompt_stale_check_in_flight = False
        self._xprompt_stale_checked_mono = completed_mono
        binding = self._stack.binding
        if binding is None:
            return
        if (
            generation != self._xprompt_target_generation
            or binding.write_path != write_path
        ):
            return
        if self._xprompt_source_stale == stale:
            return
        self._xprompt_source_stale = stale
        self._refresh_target_classes()
        self._refresh_title(self._title_mode_suffix)

    def _refresh_prompt_mode_subtitle(self) -> None:
        """Refresh the visible prompt subtitle after target-state changes."""
        if not self.is_mounted:
            return
        try:
            mode = self.active_text_area()._vim_mode
        except Exception:
            mode = "insert"
        subtitle = (
            self.insert_mode_subtitle()
            if mode == "insert"
            else self.normal_mode_subtitle()
        )
        self.set_prompt_mode_subtitle(subtitle)
