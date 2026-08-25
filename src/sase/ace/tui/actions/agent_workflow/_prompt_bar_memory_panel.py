"""Open the Memory panel from a prompt-bar ``gm`` / ``^Gm`` request."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.ace.tui.widgets import PromptInputBar
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

    from ._types import PromptContext


@dataclass(frozen=True, slots=True)
class _MemoryPromptFocus:
    """Prompt pane state restored after the memory panel closes."""

    text_area: PromptTextArea
    vim_mode: str
    cursor: tuple[int, int]


def _seed_note_from_reference(note_reference: str | None) -> str | None:
    """Convert a captured ``#memory/<stem>`` reference into a panel seed path."""
    if not note_reference:
        return None
    text = note_reference.strip()
    if text.startswith("#"):
        text = text[1:]
    if not text.startswith("memory/"):
        return None
    stem = text.removeprefix("memory/")
    if stem.endswith(".md"):
        stem = stem[: -len(".md")]
    if not stem or "/" in stem or stem.lower() == "readme":
        return None
    from sase.memory.mutation import memory_note_relative_path_for_stem

    return memory_note_relative_path_for_stem(stem)


class PromptBarMemoryPanelMixin:
    """Handle ``PromptInputBar.MemoryPanelRequested`` (and the glossary
    shortcut's ``GlossaryPanelRequested``) from the app layer.

    Both open the same Memory subtab of the Config hub -- the glossary
    shortcut is just a different seed-detection mechanism (the highlighted
    glossary term under the cursor, already resolved to a ``glossary:<slug>``
    identity by the bar) than the ``#memory/<stem>`` xprompt reference the
    plain memory shortcut captures.
    """

    _prompt_context: PromptContext | None

    def on_prompt_input_bar_memory_panel_requested(self, event: object) -> None:
        """Open the memory panel seeded from the note under the cursor."""
        from ...modals.config_hub_session import ConfigHubEntry
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.MemoryPanelRequested):
            return

        restore = self._capture_memory_prompt_focus()
        launch_workspace = self._memory_panel_launch_workspace()

        def _on_dismissed(_result: object) -> None:
            self._restore_memory_prompt_focus(restore)

        opener = getattr(self, "_open_config_center", None)
        if callable(opener):
            opener(
                "config",
                config_entry=ConfigHubEntry(
                    subtab="memory",
                    launch_workspace=launch_workspace,
                    note=_seed_note_from_reference(event.note_reference),
                ),
                on_dismissed=_on_dismissed,
            )

    def on_prompt_input_bar_glossary_panel_requested(self, event: object) -> None:
        """Open the memory panel seeded from the glossary term under the cursor."""
        from ...modals.config_hub_session import ConfigHubEntry
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.GlossaryPanelRequested):
            return

        restore = self._capture_memory_prompt_focus()
        launch_workspace = self._memory_panel_launch_workspace()

        def _on_dismissed(_result: object) -> None:
            self._restore_memory_prompt_focus(restore)

        opener = getattr(self, "_open_config_center", None)
        if callable(opener):
            opener(
                "config",
                config_entry=ConfigHubEntry(
                    subtab="memory",
                    launch_workspace=launch_workspace,
                    note=event.note_identity,
                ),
                on_dismissed=_on_dismissed,
            )

    def _memory_panel_launch_workspace(self) -> str | None:
        """Return the prompt's workspace so the panel can include it in the ring."""
        ctx = getattr(self, "_prompt_context", None)
        if ctx is None or getattr(ctx, "is_home_mode", False):
            return None
        workspace_dir = getattr(ctx, "workspace_dir", "")
        return workspace_dir or None

    def _capture_memory_prompt_focus(self) -> _MemoryPromptFocus | None:
        """Record the focused prompt pane and vim mode before the panel opens."""
        bar = self._mounted_memory_prompt_bar()
        if bar is None:
            return None
        try:
            text_area = bar.active_text_area()
            vim_mode = str(getattr(text_area, "_vim_mode", "insert") or "insert")
            cursor = text_area.cursor_location
        except Exception:
            return None
        if not isinstance(cursor, tuple) or len(cursor) != 2:
            cursor = (0, 0)
        return _MemoryPromptFocus(
            text_area=text_area,
            vim_mode=vim_mode,
            cursor=(int(cursor[0]), int(cursor[1])),
        )

    def _restore_memory_prompt_focus(self, restore: _MemoryPromptFocus | None) -> None:
        """Return focus and vim mode to the pane that opened the panel."""
        if restore is None:
            return
        text_area = restore.text_area
        if not getattr(text_area, "is_mounted", False):
            bar = self._mounted_memory_prompt_bar()
            if bar is None:
                return
            try:
                text_area = bar.active_text_area()
            except Exception:
                return
        try:
            text_area.focus()
            if restore.vim_mode == "insert":
                text_area._enter_insert_mode()
            else:
                text_area._enter_normal_mode()
            text_area.cursor_location = restore.cursor
        except Exception:
            return

    def _mounted_memory_prompt_bar(self) -> PromptInputBar | None:
        """Return the mounted prompt bar, or ``None``."""
        from ...widgets import PromptInputBar

        mounted = getattr(self, "_mounted_prompt_bar", None)
        if callable(mounted):
            bar = mounted()
            if bar is not None:
                return bar  # type: ignore[no-any-return]
        try:
            return self.query_one("#prompt-input-bar", PromptInputBar)  # type: ignore[attr-defined,no-any-return]
        except Exception:
            return None
