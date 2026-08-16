"""Loading and empty-state helpers for the agent file panel."""

from rich.text import Text


class FilePanelStateMixin:
    """Mixin for non-content file-panel states."""

    _has_displayed_content: bool
    _static_request_id: int
    _anchor_slot_key: tuple[object, str] | None
    _last_applied_scroll_row: int | None

    def _show_loading(self) -> None:
        """Display loading indicator only if panel was previously visible."""
        if not self._has_displayed_content:
            return
        text = Text()
        text.append("Loading file...\n", style="bold #87D7FF")
        text.append("Please wait while fetching changes.", style="dim")
        self._update_body(text)  # type: ignore[attr-defined]

    def show_empty(self) -> None:
        """Show empty state."""
        self._reset_content_state()  # type: ignore[attr-defined]
        self._has_displayed_content = False
        # Drop any pending static read so its result can't paint over us.
        self._cancel_static_worker()  # type: ignore[attr-defined]
        self._static_request_id += 1
        # No agent selected: this isn't a real page, so drop the anchor
        # pointer outright rather than routing through _note_slot_change.
        self._anchor_slot_key = None
        self._last_applied_scroll_row = None
        text = Text("No agent selected", style="dim italic")
        self._update_body(text, anchor=False)  # type: ignore[attr-defined]
