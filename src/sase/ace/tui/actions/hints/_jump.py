"""Jump-to-entry hint mode for left side-panel navigation."""

from __future__ import annotations

from rich.text import Text
from textual.widgets.option_list import Option

from ...widgets import AgentList, BgCmdList, ChangeSpecList
from ._types import HintMixinBase

# Ordered hint characters: 1-9, 0, a-z (36 total)
JUMP_HINT_CHARS: str = "1234567890abcdefghijklmnopqrstuvwxyz"


def _build_jump_hint_map(count: int) -> dict[str, int]:
    """Map hint char -> entry index for up to min(count, 36) entries."""
    n = min(count, len(JUMP_HINT_CHARS))
    return {JUMP_HINT_CHARS[i]: i for i in range(n)}


class JumpToEntryMixin(HintMixinBase):
    """Mixin providing jump-to-entry hint mode for left side-panels."""

    def action_jump_to_entry(self) -> None:
        """Activate jump-to-entry hint mode on the current tab's list widget."""
        if self.current_tab == "changespecs":
            count = len(self.changespecs)
        elif self.current_tab == "agents":
            count = len(self._active_panel_indices())  # type: ignore[attr-defined]
        else:  # axe
            count = len(self._axe_items)  # type: ignore[attr-defined]

        if count == 0:
            return

        hint_map = _build_jump_hint_map(count)
        # Invert: index -> label
        hint_labels: dict[int, str] = {idx: char for char, idx in hint_map.items()}

        if self.current_tab == "changespecs":
            widget = self.query_one("#list-panel", ChangeSpecList)  # type: ignore[attr-defined]
            _show_jump_hints_changespec(widget, hint_labels)
        elif self.current_tab == "agents":
            panel = self._pinned_panel_focused  # type: ignore[attr-defined]
            widget_id = (
                "#pinned-list-panel" if panel == "pinned" else "#agent-list-panel"
            )
            widget = self.query_one(widget_id, AgentList)  # type: ignore[attr-defined]
            _show_jump_hints_agent(widget, hint_labels)
        else:  # axe
            widget = self.query_one("#bgcmd-list-panel", BgCmdList)  # type: ignore[attr-defined]
            _show_jump_hints_bgcmd(widget, hint_labels)

        self._jump_mode_active = True
        self._jump_hint_map = hint_map

    def _handle_jump_key(self, key: str) -> bool:
        """Handle a keypress while in jump mode. Returns True if handled."""
        self._exit_jump_mode()
        if key in self._jump_hint_map:
            local_idx = self._jump_hint_map[key]
            if self.current_tab == "agents":
                indices = self._active_panel_indices()  # type: ignore[attr-defined]
                if local_idx < len(indices):
                    self.current_idx = indices[local_idx]
            elif self.current_tab == "changespecs":
                if local_idx < len(self.changespecs):
                    self.current_idx = local_idx
            else:  # axe
                if local_idx < len(self._axe_items):  # type: ignore[attr-defined]
                    self.current_idx = local_idx
            return True
        return True  # always consume the key to exit jump mode cleanly

    def _exit_jump_mode(self) -> None:
        """Exit jump mode and restore normal list display."""
        self._jump_mode_active = False
        self._jump_hint_map = {}
        self._refresh_current_tab()  # type: ignore[attr-defined]


# ── Hint rendering helpers ─────────────────────────────────────────────


_HINT_STYLE = "bold #FFFF00"


def _show_jump_hints_changespec(
    widget: ChangeSpecList, hint_labels: dict[int, str]
) -> None:
    """Re-render ChangeSpec list with jump hint labels prepended."""
    widget._programmatic_update = True
    options = list(widget._options)
    widget.clear_options()
    for i, opt in enumerate(options):
        label = hint_labels.get(i)
        if label is not None and opt.prompt is not None:
            new_text = Text()
            new_text.append(f"[{label}] ", style=_HINT_STYLE)
            new_text.append_text(opt.prompt)  # type: ignore[arg-type]
            widget.add_option(Option(new_text, id=opt.id))
        else:
            widget.add_option(opt)
    widget.call_later(widget._clear_programmatic_flag)


def _show_jump_hints_agent(widget: AgentList, hint_labels: dict[int, str]) -> None:
    """Re-render Agent list with jump hint labels prepended."""
    widget._programmatic_update = True
    options = list(widget._options)
    widget.clear_options()
    for i, opt in enumerate(options):
        label = hint_labels.get(i)
        if label is not None and opt.prompt is not None:
            new_text = Text()
            new_text.append(f"[{label}] ", style=_HINT_STYLE)
            new_text.append_text(opt.prompt)  # type: ignore[arg-type]
            widget.add_option(Option(new_text, id=opt.id))
        else:
            widget.add_option(opt)
    widget.call_later(widget._clear_programmatic_flag)


def _show_jump_hints_bgcmd(widget: BgCmdList, hint_labels: dict[int, str]) -> None:
    """Re-render BgCmd list with jump hint labels prepended."""
    widget._programmatic_update = True
    options = list(widget._options)
    widget.clear_options()
    for i, opt in enumerate(options):
        label = hint_labels.get(i)
        if label is not None and opt.prompt is not None:
            new_text = Text()
            new_text.append(f"[{label}] ", style=_HINT_STYLE)
            new_text.append_text(opt.prompt)  # type: ignore[arg-type]
            widget.add_option(Option(new_text, id=opt.id))
        else:
            widget.add_option(opt)
    widget._programmatic_update = False
