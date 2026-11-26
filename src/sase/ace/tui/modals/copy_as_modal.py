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

_PREVIEW_LINES = 6
_PREVIEW_LINES_NARROW = 3


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
        self._initial_highlight_index: int | None = None

    def compose(self) -> ComposeResult:
        options: list[Option] = []
        if self.context.sections:
            self._compose_sectioned(options)
        else:
            self._compose_categorized(options)

        with Container(id="copy-as-container"):
            yield Static(self.context.title, id="copy-as-title")
            yield Static(self.context.subtitle, id="copy-as-subtitle")
            yield _CopyAsOptionList(*options, id="copy-as-list")
            if self.context.preview_pane:
                yield Static("", id="copy-as-preview")
            yield Static(
                self.context.resolved_footer,
                id="copy-as-footer",
            )

    def _compose_categorized(self, options: list[Option]) -> None:
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
                self._append_row_option(options, row)

    def _compose_sectioned(self, options: list[Option]) -> None:
        by_section: dict[str, list[CopyAsRow]] = {}
        for row in self.context.rows:
            by_section.setdefault(row.section or "", []).append(row)
        for section in self.context.sections:
            rows = by_section.pop(section.id, [])
            if not rows:
                continue
            options.append(
                Option(
                    Text(
                        section.title.upper(),
                        style="bold dim" if section.dim else "bold",
                    ),
                    id=f"copy-as-section-{section.id}",
                    disabled=True,
                )
            )
            for row in rows:
                self._append_row_option(options, row)
        for leftover in by_section.pop("", []):
            self._append_row_option(options, leftover)
        for rows in by_section.values():
            for row in rows:
                self._append_row_option(options, row)

    def _append_row_option(self, options: list[Option], row: CopyAsRow) -> None:
        option_id = f"copy-as-row-{len(self._rows_by_option_id)}"
        self._rows_by_option_id[option_id] = row
        self._rows_by_key.setdefault(row.key, row)
        if (
            self._initial_highlight_index is None
            and self.context.initial_row_key is not None
            and row.key == self.context.initial_row_key
            and row.disabled_reason is None
        ):
            self._initial_highlight_index = len(options)
        options.append(
            Option(
                _render_row(
                    row,
                    key_width=self.context.key_width,
                    label_width=self.context.label_width,
                    show_gutter=self.context.wants_marker_gutter,
                ),
                id=option_id,
                disabled=row.disabled_reason is not None,
            )
        )

    def on_mount(self) -> None:
        self._set_responsive_class(self.size.width, self.size.height)
        option_list = self.query_one("#copy-as-list", _CopyAsOptionList)
        option_list.focus()
        if self._initial_highlight_index is not None:
            try:
                option_list.highlighted = self._initial_highlight_index
            except Exception:
                if option_list.highlighted is None:
                    option_list.action_first()
        elif option_list.highlighted is None:
            option_list.action_first()
        self._update_preview()

    def on_resize(self, event: events.Resize) -> None:
        self._set_responsive_class(event.size.width, event.size.height)

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        del event
        self._update_preview()

    def _set_responsive_class(self, width: int, height: int) -> None:
        self.set_class(width <= 90 or height <= 32, "-narrow")

    def _update_preview(self) -> None:
        if not self.context.preview_pane:
            return
        try:
            preview = self.query_one("#copy-as-preview", Static)
        except Exception:
            return
        row = self._highlighted_row()
        if row is None:
            preview.update(Text(""))
            preview.border_title = ""
            return
        if row.disabled_reason is not None:
            preview.update(Text(row.disabled_reason, style="$warning"))
        else:
            value = row.value if row.value is not None else row.preview
            preview.update(_preview_text(value, self.has_class("-narrow")))
        preview.border_title = _preview_title(row)

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
                self.context.resolved_unknown_key_message,
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


def _render_row(
    row: CopyAsRow,
    *,
    key_width: int = 9,
    label_width: int | None = None,
    show_gutter: bool = False,
) -> Text:
    text = Text(no_wrap=True, overflow="ellipsis")
    key_style = "dim" if row.disabled_reason is not None else "bold #00D7AF"
    label_style = "dim" if row.disabled_reason is not None else "bold"
    text.append(f"{row.key_display:<{key_width}}", style=key_style)
    if show_gutter:
        text.append(f"{row.marker or '':<2}")
    label = f"{row.label:<{label_width}}" if label_width is not None else row.label
    text.append(label, style=label_style)
    if row.preview:
        text.append("  ")
        preview_style = "yellow" if row.disabled_reason is not None else "dim"
        text.append(row.preview, style=preview_style)
    if row.badge:
        text.append("  " if not row.preview else " ")
        text.append(row.badge, style="dim")
    return text


def _preview_text(value: str, narrow: bool) -> Text:
    limit = _PREVIEW_LINES_NARROW if narrow else _PREVIEW_LINES
    lines = value.split("\n")
    if len(lines) <= limit:
        return Text(value)
    shown = Text("\n".join(lines[:limit]))
    shown.append(f"\n… +{len(lines) - limit} more lines", style="dim")
    return shown


def _preview_title(row: CopyAsRow) -> str:
    value = row.value if row.value is not None else row.preview
    lines = value.split("\n")
    size = f"{len(lines)} lines" if len(lines) > 1 else f"{len(value)} chars"
    return f"{row.key_display} · {row.label} · {size}"


__all__ = ["CopyAsContext", "CopyAsModal", "CopyAsRow"]
