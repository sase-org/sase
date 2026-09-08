"""Event handlers and shared input teardown for the ace TUI app."""

from __future__ import annotations

from ...widgets import HintInputBar
from ._hook_processing import HookInputProcessingMixin
from ._view_processing import ViewInputProcessingMixin


class InputProcessingMixin(ViewInputProcessingMixin, HookInputProcessingMixin):
    """Mixin providing input processing for hint modes."""

    def on_hint_input_bar_submitted(self, event: HintInputBar.Submitted) -> None:
        """Handle hint input submission."""
        if event.mode == "view":
            ready = getattr(self, "_agent_hint_render_ready", None)
            identity = getattr(self, "_agent_hint_render_identity", None)
            if (
                getattr(self, "current_tab", None) == "agents"
                and ready is not None
                and identity is not None
                and not ready.is_set()
            ):
                session = self._agent_hint_render_session
                self.run_worker(  # type: ignore[attr-defined]
                    self._submit_agent_view_when_ready(
                        event.value,
                        identity,
                        session,
                        ready,
                    ),
                    group="hint-view-readiness",
                    exclusive=True,
                )
                return
            self._submit_ready_view_input(event.value)
        elif event.mode == "hooks":
            self._remove_hint_input_bar()
            self._process_hooks_input(event.value)
        elif event.mode == "failed_hooks":
            self._remove_hint_input_bar()
            self._process_failed_hooks_input(event.value)
        elif event.mode == "mentors":
            self._remove_hint_input_bar()
            self._process_mentors_input(event.value)  # type: ignore[attr-defined]
        elif event.mode == "rewind":
            self._remove_hint_input_bar()
            self._process_rewind_input(event.value)  # type: ignore[attr-defined]
        else:  # accept mode
            self._remove_hint_input_bar()
            self._process_accept_input(event.value)  # type: ignore[attr-defined]

    def on_hint_input_bar_cancelled(self, event: HintInputBar.Cancelled) -> None:
        """Handle hint input cancellation."""
        del event  # unused
        self._remove_hint_input_bar()

    def _remove_hint_input_bar(self, *, refresh: bool = True) -> None:
        """Remove the hint input bar and restore normal display."""
        self._cancel_agent_hint_render_tasks()

        # Clear hint mode state first.
        self._hint_mode_active = False
        self._hint_mode_hints_for = None

        # Clear accept mode state.
        self._accept_mode_active = False

        # Clear rewind mode state.
        self._rewind_mode_active = False

        try:
            hint_bar = self.query_one("#hint-input-bar", HintInputBar)  # type: ignore[attr-defined]
            hint_bar.remove()
        except Exception:
            pass

        if refresh:
            if self.current_tab == "agents":
                self._refresh_agents_display()  # type: ignore[attr-defined]
            else:
                self._refresh_display()  # type: ignore[attr-defined]
