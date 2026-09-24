"""Sticky description panel for selected service proc, routine, or job rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.console import Console, ConsoleOptions, RenderResult
from rich.text import Text
from textual.widgets import Static

_LUMBERJACK_ACCENT = "bold #FFD700"
_CHOP_ACCENT = "#D7AF87"
_SUMMARY_STYLE = "italic #D7D7AF"
_BODY_STYLE = "#AFAF87"
_TARGET_STYLE = "dim #B87333"
_SERVICE_ACCENT = "bold #00D7AF"
_SERVICE_SUMMARY_STYLE = "italic #AFD7D7"
_SERVICE_BODY_STYLE = "#87AFAF"
_SERVICE_TARGET_STYLE = "dim #00D7AF"
_FALLBACK_STYLE = "dim italic"
_OVERFLOW_STYLE = "dim italic"
_FALLBACK = "No description configured"
_GUTTER = "▌ "
_GUTTER_WIDTH = 2


@dataclass(frozen=True)
class _DescriptionTheme:
    """Palette for one Services-tab row family."""

    accent: str
    summary: str
    body: str
    target: str


_LUMBERJACK_THEME = _DescriptionTheme(
    accent=_LUMBERJACK_ACCENT,
    summary=_SUMMARY_STYLE,
    body=_BODY_STYLE,
    target=_TARGET_STYLE,
)
_CHOP_THEME = _DescriptionTheme(
    accent=_CHOP_ACCENT,
    summary=_SUMMARY_STYLE,
    body=_BODY_STYLE,
    target=_TARGET_STYLE,
)
_SERVICE_THEME = _DescriptionTheme(
    accent=_SERVICE_ACCENT,
    summary=_SERVICE_SUMMARY_STYLE,
    body=_SERVICE_BODY_STYLE,
    target=_SERVICE_TARGET_STYLE,
)


def _starts_bullet(line: str) -> bool:
    return len(line) >= 1 and line[0] in "-*•"


def _wrapped(text: Text, console: Console, width: int) -> list[Text]:
    """Wrap rich text to a positive width without retaining source hard wraps."""
    return list(
        text.wrap(
            console,
            max(1, width),
            justify=None,
            overflow="fold",
            no_wrap=False,
        )
    ) or [Text()]


@dataclass(frozen=True)
class _DescriptionBlock:
    """Rich renderable whose measurement and paint paths share one layout."""

    summary: str
    body: str
    theme: _DescriptionTheme
    target_key: str | None
    expanded: bool
    max_lines: int
    toggle_key: str = "d"
    overflow_key: str | None = "e"

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        rows = self._rows(console, max(1, options.max_width))
        rendered = Text("\n").join(rows)
        yield rendered

    def _rows(self, console: Console, width: int) -> list[Text]:
        content_width = max(1, width - _GUTTER_WIDTH)
        summary = Text(
            self.summary.strip() or _FALLBACK,
            style=self.theme.summary if self.summary.strip() else _FALLBACK_STYLE,
        )
        if self.target_key:
            summary.append(f"  · {self.target_key}", style=self.theme.target)

        if self.expanded:
            summary_rows = _wrapped(summary, console, content_width)
        else:
            summary.truncate(content_width, overflow="ellipsis")
            summary_rows = [summary]

        hint = f"▾ {self.toggle_key}" if self.expanded else f"▸ {self.toggle_key}"
        hint_width = Text(hint).cell_len
        first_width = summary_rows[0].cell_len
        if self.body.strip() and content_width - first_width >= hint_width + 1:
            summary_rows[0].append(" " * (content_width - first_width - hint_width))
            summary_rows[0].append(hint, style=f"dim {self.theme.accent}")

        rows: list[tuple[Text, bool]] = [(row, True) for row in summary_rows]
        if self.expanded and self.body.strip():
            rows.append((Text(), False))
            rows.extend((row, False) for row in self._body_rows(console, content_width))

        max_lines = max(1, self.max_lines)
        if len(rows) > max_lines:
            dropped = len(rows) - (max_lines - 1)
            rows = rows[: max_lines - 1]
            if self.overflow_key:
                overflow = Text(
                    f"… +{dropped} more · {self.overflow_key}",
                    style=_OVERFLOW_STYLE,
                )
            else:
                overflow = Text(f"… +{dropped} more", style=_OVERFLOW_STYLE)
            rows.append((overflow, False))

        return [self._with_gutter(row, summary=is_summary) for row, is_summary in rows]

    def _body_rows(self, console: Console, content_width: int) -> list[Text]:
        blocks: list[list[str]] = []
        current: list[str] = []
        for line in self.body.splitlines():
            if line.strip():
                current.append(line.rstrip())
            elif current:
                blocks.append(current)
                current = []
        if current:
            blocks.append(current)

        rows: list[Text] = []
        for index, block in enumerate(blocks):
            if index:
                rows.append(Text())
            if _starts_bullet(block[0]):
                rows.extend(self._bullet_rows(block, console, content_width))
            else:
                paragraph = " ".join(line.strip() for line in block)
                rows.extend(
                    _wrapped(
                        Text(paragraph, style=self.theme.body), console, content_width
                    )
                )
        return rows

    def _bullet_rows(
        self, block: list[str], console: Console, content_width: int
    ) -> list[Text]:
        bullets: list[str] = []
        current: list[str] = []
        for line in block:
            if _starts_bullet(line):
                if current:
                    bullets.append(" ".join(current))
                current = [line[1:].strip()]
            elif current:
                current.append(line.strip())
        if current:
            bullets.append(" ".join(current))

        rows: list[Text] = []
        if content_width <= 2:
            return [Text("•", style=f"dim {self.theme.body}") for _ in bullets]
        for bullet in bullets:
            wrapped = _wrapped(
                Text(bullet, style=self.theme.body),
                console,
                content_width - 2,
            )
            for index, wrapped_line in enumerate(wrapped):
                prefix = Text(
                    "• " if index == 0 else "  ", style=f"dim {self.theme.body}"
                )
                prefix.append_text(wrapped_line)
                rows.append(prefix)
        return rows

    def _with_gutter(self, row: Text, *, summary: bool) -> Text:
        accent = self.theme.accent if summary else f"dim {self.theme.accent}"
        rendered = Text(_GUTTER, style=accent)
        rendered.append_text(row)
        return rendered


@dataclass(frozen=True)
class _ShownDescription:
    summary: str
    body: str
    theme: _DescriptionTheme
    target_key: str | None
    overflow_key: str | None


class AxeDescriptionBanner(Static):
    """Render the selected service proc, routine, or job description."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the panel hidden until a configuration row is selected."""
        super().__init__("", **kwargs)
        self._shown: _ShownDescription | None = None
        self._expanded = True
        self._max_lines = 10
        self._toggle_key = "d"
        self._edit_key = "e"
        self._description_renderable = self._build_renderable()
        self.display = False

    def render(self) -> _DescriptionBlock:
        """Return the cached renderable without requiring an app mount."""
        return self._description_renderable

    def show_lumberjack(self, name: str, summary: str, body: str) -> None:
        """Show a lumberjack description using the top-level AXE accent."""
        del name
        self._show(
            summary,
            body,
            theme=_LUMBERJACK_THEME,
            overflow_key=self._edit_key,
        )

    def show_chop(
        self,
        chop_name: str,
        summary: str,
        body: str,
        *,
        generated: bool = False,
        target_key: str | None = None,
    ) -> None:
        """Show a chop description and optional generated-target chip."""
        del chop_name
        self._show(
            summary,
            body,
            theme=_CHOP_THEME,
            target_key=target_key if generated else None,
            overflow_key=self._edit_key,
        )

    def show_service_proc(self, name: str, summary: str, body: str) -> None:
        """Show a service proc description using the service teal accent."""
        del name
        self._show(
            summary,
            body,
            theme=_SERVICE_THEME,
            overflow_key=None,
        )

    def set_keys(self, *, toggle_key: str, edit_key: str) -> None:
        """Store the configured display keys, repainting only on change."""
        if self._toggle_key == toggle_key and self._edit_key == edit_key:
            return
        self._toggle_key = toggle_key
        self._edit_key = edit_key
        if self._shown is not None and self._shown.overflow_key is not None:
            self._shown = _ShownDescription(
                summary=self._shown.summary,
                body=self._shown.body,
                theme=self._shown.theme,
                target_key=self._shown.target_key,
                overflow_key=edit_key,
            )
        self._rerender()

    def set_expanded(self, expanded: bool) -> None:
        """Set the in-memory panel state and repaint the cached description."""
        if self._expanded == expanded:
            return
        self._expanded = expanded
        self._rerender()

    def set_max_lines(self, max_lines: int) -> None:
        """Set the authoritative rendered-line cap."""
        normalized = max(1, int(max_lines))
        if self._max_lines == normalized:
            return
        self._max_lines = normalized
        self._rerender()

    def hide(self) -> None:
        """Remove the panel from layouts without a selected AXE config row."""
        self.display = False

    def _show(
        self,
        summary: str,
        body: str,
        *,
        theme: _DescriptionTheme,
        target_key: str | None = None,
        overflow_key: str | None = "e",
    ) -> None:
        shown = _ShownDescription(
            summary=summary,
            body=body,
            theme=theme,
            target_key=target_key,
            overflow_key=overflow_key,
        )
        if self.display and self._shown == shown:
            return
        self._shown = shown
        self.display = True
        self._rerender()

    def _rerender(self) -> None:
        self._description_renderable = self._build_renderable()
        if self.is_attached:
            self.refresh(layout=True)

    def _build_renderable(self) -> _DescriptionBlock:
        shown = self._shown
        return _DescriptionBlock(
            summary=shown.summary if shown is not None else "",
            body=shown.body if shown is not None else "",
            theme=shown.theme if shown is not None else _LUMBERJACK_THEME,
            target_key=shown.target_key if shown is not None else None,
            expanded=self._expanded,
            max_lines=self._max_lines,
            toggle_key=self._toggle_key,
            overflow_key=shown.overflow_key if shown is not None else self._edit_key,
        )
