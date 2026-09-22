"""Responsive Rich renderable used by the agent detail header."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from rich.console import Console, ConsoleOptions, RenderResult
from rich.style import StyleType
from rich.text import Span, Text

from ._agent_page_section import ResponsiveAgentPageSection
from ._agent_bead_section import ResponsiveBeadSection
from ._agent_plan_section import ResponsivePlanSection
from ._agent_shell_section import ResponsiveShellSection
from ._agent_slow_tools_detail import ResponsiveSlowToolCallsSection
from ._agent_wait_section import ResponsiveWaitSection

if TYPE_CHECKING:
    from ._identity_header import IdentityHeader

type ResponsiveHeaderSection = (
    ResponsiveAgentPageSection
    | ResponsiveBeadSection
    | ResponsivePlanSection
    | ResponsiveShellSection
    | ResponsiveSlowToolCallsSection
    | ResponsiveWaitSection
)


class AgentHeaderRenderable:
    """Mutable logical header with retained responsive context sections."""

    __slots__ = ("_identity_header", "_sections", "_text")

    def __init__(
        self,
        text: Text,
        sections: tuple[tuple[int, int, ResponsiveHeaderSection], ...],
        *,
        identity_header: IdentityHeader | None = None,
    ) -> None:
        self._text = text
        self._sections = sections
        self._identity_header = identity_header

    @property
    def identity_header(self) -> IdentityHeader | None:
        """Return the identity detached from this document, if any."""
        return self._identity_header

    def with_identity_header(self, identity_header: IdentityHeader | None) -> Self:
        """Attach an identity to this document and return it for chaining."""
        self._identity_header = identity_header
        return self

    @property
    def plain(self) -> str:
        """Return the complete logical header text for inspection and search."""
        return self._text.plain

    @property
    def spans(self) -> list[Span]:
        """Return logical text spans, including responsive section fields."""
        return self._text.spans

    @property
    def end(self) -> str:
        """Return the Rich line ending applied after this header renderable."""
        return self._text.end

    @end.setter
    def end(self, value: str) -> None:
        """Set the Rich line ending applied after this header renderable."""
        self._text.end = value

    def append(
        self,
        text: str | Text,
        style: StyleType | None = None,
    ) -> Self:
        """Append content after responsive sections without moving them."""
        self._text.append(text, style=style)
        return self

    def append_text(self, text: Text) -> Self:
        """Append styled Rich text after responsive sections."""
        self._text.append_text(text)
        return self

    def stylize(
        self,
        style: StyleType,
        start: int = 0,
        end: int | None = None,
    ) -> None:
        """Apply a Rich style to a logical header range."""
        self._text.stylize(style, start, end)

    def __rich_console__(
        self,
        _console: Console,
        _options: ConsoleOptions,
    ) -> RenderResult:
        cursor = 0
        for start, end, section in self._sections:
            prefix = self._text[cursor:start]
            prefix.end = ""
            yield prefix
            yield section
            cursor = end

        suffix = self._text[cursor:]
        suffix.end = self._text.end
        yield suffix


AgentHeader = Text | AgentHeaderRenderable
