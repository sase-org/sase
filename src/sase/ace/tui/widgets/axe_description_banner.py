"""Always-visible description panel for selected AXE configuration rows."""

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
_FALLBACK_STYLE = "dim italic"
_OVERFLOW_STYLE = "dim italic"
_FALLBACK = "No description configured"
_GUTTER = "▌ "
_GUTTER_WIDTH = 2


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
    accent_style: str
    target_key: str | None
    expanded: bool
    max_lines: int

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
            style=_SUMMARY_STYLE if self.summary.strip() else _FALLBACK_STYLE,
        )
        if self.target_key:
            summary.append(f"  · {self.target_key}", style=_TARGET_STYLE)

        if self.expanded:
            summary_rows = _wrapped(summary, console, content_width)
        else:
            summary.truncate(content_width, overflow="ellipsis")
            summary_rows = [summary]

        hint = "▾ d" if self.expanded else "▸ d"
        first_width = summary_rows[0].cell_len
        if self.body.strip() and content_width - first_width >= len(hint) + 1:
            summary_rows[0].append(" " * (content_width - first_width - len(hint)))
            summary_rows[0].append(hint, style=f"dim {self.accent_style}")

        rows: list[tuple[Text, bool]] = [(row, True) for row in summary_rows]
        if self.expanded and self.body.strip():
            rows.append((Text(), False))
            rows.extend((row, False) for row in self._body_rows(console, content_width))

        max_lines = max(1, self.max_lines)
        if len(rows) > max_lines:
            dropped = len(rows) - (max_lines - 1)
            rows = rows[: max_lines - 1]
            rows.append((Text(f"… +{dropped} more · e", style=_OVERFLOW_STYLE), False))

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
                    _wrapped(Text(paragraph, style=_BODY_STYLE), console, content_width)
                )
        return rows

    @staticmethod
    def _bullet_rows(
        block: list[str], console: Console, content_width: int
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
            return [Text("•", style=f"dim {_BODY_STYLE}") for _ in bullets]
        for bullet in bullets:
            wrapped = _wrapped(
                Text(bullet, style=_BODY_STYLE),
                console,
                content_width - 2,
            )
            for index, wrapped_line in enumerate(wrapped):
                prefix = Text("• " if index == 0 else "  ", style=f"dim {_BODY_STYLE}")
                prefix.append_text(wrapped_line)
                rows.append(prefix)
        return rows

    def _with_gutter(self, row: Text, *, summary: bool) -> Text:
        accent = self.accent_style if summary else f"dim {self.accent_style}"
        rendered = Text(_GUTTER, style=accent)
        rendered.append_text(row)
        return rendered


@dataclass(frozen=True)
class _ShownDescription:
    summary: str
    body: str
    accent_style: str
    target_key: str | None


class AxeDescriptionBanner(Static):
    """Render the selected lumberjack or chop description."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the panel hidden until a configuration row is selected."""
        super().__init__("", **kwargs)
        self._shown: _ShownDescription | None = None
        self._expanded = True
        self._max_lines = 10
        self._description_renderable = self._build_renderable()
        self.display = False

    def render(self) -> _DescriptionBlock:
        """Return the cached renderable without requiring an app mount."""
        return self._description_renderable

    def show_lumberjack(self, name: str, summary: str, body: str) -> None:
        """Show a lumberjack description using the top-level AXE accent."""
        del name
        self._show(summary, body, accent_style=_LUMBERJACK_ACCENT)

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
            accent_style=_CHOP_ACCENT,
            target_key=target_key if generated else None,
        )

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
        accent_style: str,
        target_key: str | None = None,
    ) -> None:
        self._shown = _ShownDescription(
            summary=summary,
            body=body,
            accent_style=accent_style,
            target_key=target_key,
        )
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
            accent_style=(
                shown.accent_style if shown is not None else _LUMBERJACK_ACCENT
            ),
            target_key=shown.target_key if shown is not None else None,
            expanded=self._expanded,
            max_lines=self._max_lines,
        )
