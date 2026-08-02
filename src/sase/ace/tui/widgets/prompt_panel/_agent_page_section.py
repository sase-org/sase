"""Responsive hosted-page lane for the agent detail header."""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Console, ConsoleOptions, RenderResult
from rich.text import Text

AGENT_PAGE_SECTION_ID = "agent-page"
AGENT_PAGE_FIELD_LABEL = "Page: "
AGENT_PAGE_FIELD_LABEL_STYLE = "bold #87D7FF"
_AGENT_PAGE_URL_STYLE = "bold underline #569CD6"


@dataclass(slots=True)
class ResponsiveAgentPageSection:
    """One hosted page URL that truncates instead of wrapping."""

    url: str

    @property
    def logical_text(self) -> Text:
        """Return the complete styled page lane used for inspection."""
        text = Text(end="")
        text.append(AGENT_PAGE_FIELD_LABEL, style=AGENT_PAGE_FIELD_LABEL_STYLE)
        text.append(f"{self.url}\n", style=_AGENT_PAGE_URL_STYLE)
        return text

    def __rich_console__(
        self,
        _console: Console,
        _options: ConsoleOptions,
    ) -> RenderResult:
        text = Text(end="", no_wrap=True, overflow="ellipsis")
        text.append(AGENT_PAGE_FIELD_LABEL, style=AGENT_PAGE_FIELD_LABEL_STYLE)
        text.append(f"{self.url}\n", style=_AGENT_PAGE_URL_STYLE)
        yield text


__all__ = [
    "AGENT_PAGE_FIELD_LABEL",
    "AGENT_PAGE_FIELD_LABEL_STYLE",
    "AGENT_PAGE_SECTION_ID",
    "ResponsiveAgentPageSection",
]
