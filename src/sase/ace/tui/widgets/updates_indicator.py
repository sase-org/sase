"""Persistent updates-available indicator widget for the ace TUI."""

from typing import Any

from rich.text import Text
from textual.widgets import Static

from .update_accents import (
    AGENT_CLI_ACCENT as _AGENT_CLI_ACCENT,
    CORE_UPDATE_ACCENT as _CORE_UPDATE_ACCENT,
    UPDATE_GLYPH as _UPDATE_GLYPH,
    UPDATES_ACCENT as _UPDATES_ACCENT,
)

_CORE_UPDATE_GLYPH = "*"


class UpdatesAvailableIndicator(Static):
    """Top-bar badge showing known SASE and agent-CLI updates."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            self._build_content(0, core=False, agent_cli_count=0),
            **kwargs,
        )
        self._count = 0
        self._agent_cli_count = 0
        self._manual_agent_cli_count = 0
        self._core = False
        self.tooltip = self._build_tooltip(
            0,
            core=False,
            agent_cli_count=0,
            manual_agent_cli_count=0,
        )

    @property
    def count(self) -> int:
        """Aggregate number of available updates currently shown."""
        return self._count + self._agent_cli_count

    @property
    def sase_count(self) -> int:
        """Number of SASE/core/plugin updates currently shown."""
        return self._count

    @property
    def core(self) -> bool:
        """Whether the current badge signals a pending core rebuild."""
        return self._core

    @property
    def agent_cli_count(self) -> int:
        """Number of available agent-CLI updates currently shown."""
        return self._agent_cli_count

    @property
    def manual_agent_cli_count(self) -> int:
        """Number of shown agent-CLI updates requiring manual action."""
        return self._manual_agent_cli_count

    def set_available(
        self,
        count: int,
        *,
        core: bool = False,
        agent_cli_count: int = 0,
        manual_agent_cli_count: int = 0,
    ) -> None:
        """Update the segmented badge state, hiding it when both counts are zero."""
        count = max(0, count)
        agent_cli_count = max(0, agent_cli_count)
        manual_agent_cli_count = min(
            agent_cli_count,
            max(0, manual_agent_cli_count),
        )
        core = bool(core and count > 0)
        if (
            self._count == count
            and self._agent_cli_count == agent_cli_count
            and self._manual_agent_cli_count == manual_agent_cli_count
            and self._core == core
        ):
            return
        self._count = count
        self._agent_cli_count = agent_cli_count
        self._manual_agent_cli_count = manual_agent_cli_count
        self._core = core
        self.tooltip = self._build_tooltip(
            count,
            core=core,
            agent_cli_count=agent_cli_count,
            manual_agent_cli_count=manual_agent_cli_count,
        )
        if self.is_mounted:
            self.update(
                self._build_content(
                    count,
                    core=core,
                    agent_cli_count=agent_cli_count,
                )
            )

    async def on_click(self) -> None:
        """Open the Admin Center's Updates tab."""
        await self.app.run_action("open_updates_panel")

    @staticmethod
    def _build_content(
        count: int,
        *,
        core: bool = False,
        agent_cli_count: int = 0,
    ) -> Text:
        """Build joined domain-specific badge segments without doing I/O."""
        text = Text()
        if count > 0:
            suffix = f" {_CORE_UPDATE_GLYPH}" if core else ""
            accent = _CORE_UPDATE_ACCENT if core else _UPDATES_ACCENT
            text.append(
                f" {_UPDATE_GLYPH} {count}{suffix} ",
                style=f"bold #1a1a1a on {accent}",
            )
        if agent_cli_count > 0:
            prefix = " " if count <= 0 else ""
            text.append(
                f"{prefix}CLI {_UPDATE_GLYPH} {agent_cli_count} ",
                style=f"bold #1a1a1a on {_AGENT_CLI_ACCENT}",
            )
        return text

    @staticmethod
    def _build_tooltip(
        count: int,
        *,
        core: bool = False,
        agent_cli_count: int = 0,
        manual_agent_cli_count: int = 0,
    ) -> str:
        """Build the hover tooltip with separate, truthful domain counts."""
        if count <= 0 and agent_cli_count <= 0:
            return "No updates available"
        domains: list[str] = []
        if count > 0:
            noun = "update" if count == 1 else "updates"
            domains.append(f"{count} SASE/core/plugin {noun}")
        if agent_cli_count > 0:
            noun = "update" if agent_cli_count == 1 else "updates"
            domains.append(f"{agent_cli_count} agent CLI {noun}")
        detail = " and ".join(domains) + " available."
        if core:
            detail += (
                " Includes sase-core "
                "(Rust rebuild, expect a slower update). Click to open Updates, "
                "or press ,U to update the eligible set from the latest "
                "completed background check."
            )
        else:
            detail += (
                " Click to open Updates, or press ,U to update the eligible set "
                "from the latest completed background check."
            )
        if manual_agent_cli_count > 0:
            noun = "update" if manual_agent_cli_count == 1 else "updates"
            detail += (
                f" {manual_agent_cli_count} agent CLI {noun} require"
                f"{'s' if manual_agent_cli_count == 1 else ''} manual action."
            )
        return detail
