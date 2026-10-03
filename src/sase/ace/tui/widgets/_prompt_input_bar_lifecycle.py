"""Composition and mount lifecycle for ``PromptInputBar``."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
from sase.ace.tui.widgets.prompt_stack import PromptStackState
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from textual.widget import Widget
    from textual.widgets import Static as _MixinBase
else:
    _MixinBase = object


class PromptInputBarLifecycleMixin(_MixinBase):
    """Widget composition and mount-time warmup."""

    if TYPE_CHECKING:
        _initial_cursor: tuple[int, int] | None
        _mode: str
        _placeholder: str
        _stack: PromptStackState
        _title_mode_suffix: str

        def _apply_active_classes(self) -> None: ...
        def _build_pane_widgets(self) -> list[Widget]: ...
        def _clamp_cursor_location(
            self,
            text_area: PromptTextArea,
            cursor: tuple[int, int],
        ) -> tuple[int, int]: ...
        def _compute_placeholder(self) -> str: ...
        def _cursor_to_end(self, text_area: PromptTextArea) -> None: ...
        def _refresh_dispatch_context_line(self) -> None: ...
        def _refresh_title(self, mode_suffix: str = "") -> None: ...
        def _schedule_height_update(self) -> None: ...
        def _schedule_xprompt_stale_check(self, *, force: bool = False) -> None: ...
        def _sync_todo_counts_from_mounted_panes(self) -> None: ...
        def _warm_dispatch_target_catalog(self) -> None: ...
        def active_text_area(self) -> PromptTextArea: ...
        def auto_show_frontmatter_panel(self) -> None: ...
        def insert_mode_subtitle(self) -> str: ...
        def refresh_cursor_readouts(self) -> None: ...
        def set_prompt_mode_subtitle(self, subtitle: str) -> None: ...

    def compose(self) -> ComposeResult:
        """Compose the input bar: completion / leader panels, then stack.

        The frontmatter panel sits directly above ``#prompt-stack`` (prompt mode
        only -- feedback / approve-prompt bars are not multi-agent surfaces) and
        starts hidden, auto-showing on mount when the prompt already carries
        frontmatter; otherwise the user opens it with ``g=``.
        """
        self._placeholder = self._compute_placeholder()
        yield Static("", id="prompt-completion", classes="hidden")
        if self._mode == "prompt":
            yield FrontmatterPanel(
                self._stack.frontmatter,
                id="frontmatter-panel",
                classes="hidden",
            )
            yield Static("", id="prompt-dispatch-context", classes="hidden")
        yield Static("", id="prompt-g-prefix-hints", classes="hidden")
        yield Static("", id="prompt-search-command", classes="hidden")
        with Vertical(id="prompt-stack"):
            yield from self._build_pane_widgets()

    def on_mount(self) -> None:
        """Focus the active pane on mount and position its cursor at end."""
        # Phase ``tick-compare-skip``: publish the mounted bar so
        # ``_prompt_input_active`` stays O(1). Every prompt mode (prompt,
        # home, feedback, approve) mounts through this widget.
        try:
            self.app._active_prompt_bar = self  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - explicit state is best-effort.
            pass
        text_area = self.active_text_area()
        self.watch(self.app, "theme", self._app_theme_changed, init=False)
        self._sync_todo_counts_from_mounted_panes()
        text_area.focus()
        if self._initial_cursor is not None:
            text_area.cursor_location = self._clamp_cursor_location(
                text_area,
                self._initial_cursor,
            )
        else:
            self._cursor_to_end(text_area)

        # Complete a `<space>` key-to-paint sample: the bar is now mounted
        # and focused (the model update); the paint lands on the next
        # refresh. Other mounts leave foreign samples alone.
        perf = getattr(self.app, "_jk_perf", None)
        if perf is not None and perf.inflight_action == "prompt_space":
            perf.mark_model_updated()
            self.app.call_after_refresh(perf.mark_painted)

        # Border title and subtitle
        self._refresh_title()
        self.set_prompt_mode_subtitle(self.insert_mode_subtitle())
        if self._mode in ("feedback", "approve_prompt"):
            self.add_class("feedback-mode")
        self._schedule_xprompt_stale_check(force=True)
        # First-keystroke essentials stay synchronous: xprompt assist entries
        # and the VCS project completion catalog were measured, and moving
        # them would delay the first keystroke.
        text_area._warm_current_xprompt_assist_entries()
        text_area._warm_vcs_project_completion_catalog()
        text_area._on_prompt_completion_context_changed()
        self._refresh_dispatch_context_line()
        self._apply_active_classes()
        self.auto_show_frontmatter_panel()
        self._schedule_height_update()
        self.refresh_cursor_readouts()
        self._schedule_deferred_mount_warmups()

    def _schedule_deferred_mount_warmups(self) -> None:
        """Defer non-essential catalog warm-ups one paint past first paint.

        Phase ``post-open-quiet``: the bar paints (focus, cursor, chrome, and
        first-keystroke completion) before the artifact-ref, model,
        path-inventory, history-word, prediction, placeholder, and
        dispatch-target warm-ups run.
        """
        try:
            self.app.call_after_refresh(self._run_deferred_mount_warmups)
        except Exception:
            self._run_deferred_mount_warmups()

    def _run_deferred_mount_warmups(self) -> None:
        """Run the warm-ups deferred by :meth:`_schedule_deferred_mount_warmups`."""
        try:
            if not self.is_mounted:
                return
            text_area = self.active_text_area()
        except Exception:
            return
        warmups = (
            text_area._warm_current_artifact_ref_completion_catalog,
            text_area._warm_model_completion_catalog,
            text_area._warm_prompt_path_inventory,
            text_area._warm_history_word_completion_cache,
            text_area._warm_prompt_prediction_cache,
            text_area._warm_common_placeholder_cache,
            self._warm_dispatch_target_catalog,
        )
        for warm in warmups:
            try:
                warm()
            except Exception:
                log.debug("Deferred prompt-bar warmup failed", exc_info=True)

    def on_unmount(self) -> None:
        """Withdraw the explicit prompt-active reference for this bar."""
        try:
            app = self.app
        except Exception:  # noqa: BLE001 - teardown has no active app.
            return
        try:
            if getattr(app, "_active_prompt_bar", None) is self:
                app._active_prompt_bar = None  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - explicit state is best-effort.
            pass

    def _app_theme_changed(self) -> None:
        """Recompose theme-derived title chrome after an app theme switch."""
        if self.is_mounted:
            self._refresh_title(self._title_mode_suffix)
