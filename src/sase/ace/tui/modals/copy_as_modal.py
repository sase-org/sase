"""Compact registry-driven picker for ACE copy targets."""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from ..copy_targets import CopyTargetCategory
from .copy_as_types import CopyAsContext, CopyAsRow


_CATEGORY_ORDER: tuple[CopyTargetCategory, ...] = (
    "Identity",
    "Location",
    "Content",
    "Data",
    "Actions",
)


class _CopyAsOptionList(OptionList):
    """Option list that gives configured accelerators first refusal."""

    async def _on_key(self, event: events.Key) -> None:
        screen = self.screen
        if isinstance(screen, CopyAsModal) and screen._handle_palette_key(event):
            return
        await super()._on_key(event)


class CopyAsModal(ModalScreen[CopyAsRow | None]):
    """Grouped, mouse-friendly picker for the active copy context."""

    def __init__(self, context: CopyAsContext) -> None:
        super().__init__()
        self.context = context
        self._rows_by_option_id: dict[str, CopyAsRow] = {}
        self._rows_by_key: dict[str, CopyAsRow] = {}

    def compose(self) -> ComposeResult:
        options: list[Option] = []
        for category in _CATEGORY_ORDER:
            rows = tuple(row for row in self.context.rows if row.category == category)
            if not rows:
                continue
            options.append(
                Option(
                    Text(category.upper(), style="bold dim"),
                    id=f"copy-as-category-{category.casefold()}",
                    disabled=True,
                )
            )
            for row in rows:
                option_id = f"copy-as-row-{len(self._rows_by_option_id)}"
                self._rows_by_option_id[option_id] = row
                self._rows_by_key.setdefault(row.key, row)
                options.append(
                    Option(
                        _render_row(row),
                        id=option_id,
                        disabled=row.disabled_reason is not None,
                    )
                )

        with Container(id="copy-as-container"):
            yield Static("Copy as…", id="copy-as-title")
            yield Static(self.context.subtitle, id="copy-as-subtitle")
            yield _CopyAsOptionList(*options, id="copy-as-list")
            yield Static(
                "enter select  ·  j/k or ↑/↓ navigate  ·  q/esc cancel",
                id="copy-as-footer",
            )

    def on_mount(self) -> None:
        self._set_responsive_class(self.size.width, self.size.height)
        option_list = self.query_one("#copy-as-list", _CopyAsOptionList)
        option_list.focus()
        if option_list.highlighted is None:
            option_list.action_first()

    def on_resize(self, event: events.Resize) -> None:
        self._set_responsive_class(event.size.width, event.size.height)

    def _set_responsive_class(self, width: int, height: int) -> None:
        self.set_class(width <= 90 or height <= 32, "-narrow")

    def _handle_palette_key(self, event: events.Key) -> bool:
        """Handle one key, preserving configured-key precedence."""

        key = event.key
        if key == "escape":
            self._consume(event)
            self.dismiss(None)
            return True

        row = self._rows_by_key.get(key)
        if row is not None:
            self._consume(event)
            if row.disabled_reason is not None:
                self.app.notify(row.disabled_reason, severity="warning")
                return True
            self.dismiss(row)
            return True

        if key == "enter":
            self._consume(event)
            row = self._highlighted_row()
            if row is not None:
                self.dismiss(row)
            return True
        if key in {"j", "down", "ctrl+n"}:
            self._consume(event)
            self.query_one("#copy-as-list", OptionList).action_cursor_down()
            return True
        if key in {"k", "up", "ctrl+p"}:
            self._consume(event)
            self.query_one("#copy-as-list", OptionList).action_cursor_up()
            return True
        if key == "q":
            self._consume(event)
            self.dismiss(None)
            return True
        if event.character and event.character.isprintable():
            self._consume(event)
            self.app.notify(
                self.context.unknown_key_message,
                severity="warning",
            )
            return True
        return False

    def _highlighted_row(self) -> CopyAsRow | None:
        option_list = self.query_one("#copy-as-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        try:
            option = option_list.get_option_at_index(highlighted)
        except Exception:
            return None
        return self._rows_by_option_id.get(str(option.id))

    def on_option_list_option_selected(
        self,
        event: OptionList.OptionSelected,
    ) -> None:
        row = self._rows_by_option_id.get(str(event.option.id))
        if row is None:
            return
        event.stop()
        self.dismiss(row)

    @staticmethod
    def _consume(event: events.Key) -> None:
        event.prevent_default()
        event.stop()


def _render_row(row: CopyAsRow) -> Text:
    text = Text(no_wrap=True, overflow="ellipsis")
    key_style = "dim" if row.disabled_reason is not None else "bold #00D7AF"
    label_style = "dim" if row.disabled_reason is not None else "bold"
    text.append(f"{row.key_display:<9}", style=key_style)
    text.append(row.label, style=label_style)
    if row.preview:
        text.append("  ")
        preview_style = "yellow" if row.disabled_reason is not None else "dim"
        text.append(row.preview, style=preview_style)
    return text


__all__ = ["CopyAsContext", "CopyAsModal", "CopyAsRow"]
