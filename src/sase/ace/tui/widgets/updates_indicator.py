"""Persistent updates-available indicator widget for sase's TUI."""

from collections.abc import Sequence
from typing import Any

from rich.text import Text

from sase.ace.tui.proc_gear_chips import update_gear_chip
from sase.ace.tui.update_gear import (
    PendingUpdateRestart,
    UpdateGearState,
    resolve_update_gear,
    restart_pending_tooltip,
)

from .top_bar_group import TopBarGroup
from .update_accents import (
    AGENT_CLI_ACCENT as _AGENT_CLI_ACCENT,
    UPDATE_GLYPH as _UPDATE_GLYPH,
    UPDATES_ACCENT as _UPDATES_ACCENT,
    UPDATES_SURFACE as _UPDATES_SURFACE,
    build_core_tag as _build_core_tag,
)


class UpdatesAvailableIndicator(TopBarGroup):
    """Top-bar badge showing known SASE and agent-CLI updates.

    Renders as ``updates: ⬆ N`` with the top bar's only deep chip (moss
    surface, lime ink). The SASE/plugin segment always uses the identity
    style; a pending sase-core Rust rebuild appends the inset ``core`` tag;
    the agent-CLI segment shares the moss surface with sage ink. Each
    segment carries its own padding so it reads as its own part of the
    chip. The gear inset leads the badge in one of three states (green
    updating, yellow restart queued, red last update failed) with
    precedence green > yellow > red. Clicking opens the Admin Center's
    Updates tab, the Procs tab on the running update while one runs, or
    the Procs tab on the first restart blocker while a restart is queued.
    """

    GROUP_LABEL = "updates"
    CLICK_ACTION = "open_updates_panel"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._count = 0
        self._agent_cli_count = 0
        self._manual_agent_cli_count = 0
        self._core = False
        self._running_labels: tuple[str, ...] = ()
        self._pending_restart: PendingUpdateRestart | None = None
        self._refresh_state()

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

    @property
    def running_count(self) -> int:
        """Number of running update procs currently shown."""
        return len(self._running_labels)

    @property
    def gear_state(self) -> UpdateGearState | None:
        """Return the single visible gear following green > yellow > red."""
        return resolve_update_gear(
            updating=bool(self._running_labels),
            restart_pending=self._pending_restart is not None,
            failed=False,
        )

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
        self._refresh_state()

    def set_running(self, labels: Sequence[str]) -> None:
        """Update the running-update gear state from proc-observer labels."""
        next_labels = tuple(labels)
        if next_labels == self._running_labels:
            return
        self._running_labels = next_labels
        self._refresh_state()

    def set_restart_pending(self, pending: PendingUpdateRestart | None) -> None:
        """Update the restart-queued gear state, ignoring equal values."""
        if pending == self._pending_restart:
            return
        self._pending_restart = pending
        self._refresh_state()

    def _refresh_state(self) -> None:
        """Refresh body and tooltip from the independent available/running inputs."""
        self._set_body(
            self._build_content(
                self._count,
                core=self._core,
                agent_cli_count=self._agent_cli_count,
                gear=self.gear_state,
            )
        )
        tooltip = self._build_tooltip(
            self._count,
            core=self._core,
            agent_cli_count=self._agent_cli_count,
            manual_agent_cli_count=self._manual_agent_cli_count,
            running_labels=self._running_labels,
            pending_restart=self._pending_restart,
        )
        if self.tooltip != tooltip:
            self.tooltip = tooltip

    async def on_click(self, event: object | None = None) -> None:
        """Open the gear target in Procs while a gear shows, else Updates.

        Textual dispatches ``on_click`` for every class in the MRO that
        defines it, so calling ``super().on_click()`` would run the base
        group handler a second time. Prevent the default instead and run
        exactly one action here.
        """
        prevent = getattr(event, "prevent_default", None)
        if callable(prevent):
            try:
                prevent()
            except Exception:
                pass
        stop = getattr(event, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:
                pass
        gear = self.gear_state
        if gear == "updating":
            await self.app.run_action("open_update_procs")
            return
        if gear == "restart_pending":
            await self.app.run_action("open_restart_blockers")
            return
        if self.CLICK_ACTION is None:
            return
        await self.app.run_action(self.CLICK_ACTION)

    @staticmethod
    def _build_content(
        count: int,
        *,
        core: bool = False,
        agent_cli_count: int = 0,
        gear: UpdateGearState | None = None,
    ) -> Text:
        """Build the deep-chip body: gear inset, identity segment, core tag, CLI segment."""
        text = Text()
        if gear is not None:
            text.append_text(update_gear_chip(gear))
        if count > 0:
            text.append(
                f" {_UPDATE_GLYPH} {count} ",
                style=f"bold {_UPDATES_ACCENT} on {_UPDATES_SURFACE}",
            )
            if core:
                text.append_text(_build_core_tag())
        if agent_cli_count > 0:
            text.append(
                f" CLI {_UPDATE_GLYPH} {agent_cli_count} ",
                style=f"bold {_AGENT_CLI_ACCENT} on {_UPDATES_SURFACE}",
            )
        return text

    @staticmethod
    def _build_tooltip(
        count: int,
        *,
        core: bool = False,
        agent_cli_count: int = 0,
        manual_agent_cli_count: int = 0,
        running_labels: Sequence[str] = (),
        pending_restart: PendingUpdateRestart | None = None,
    ) -> str:
        """Build the hover tooltip with separate, truthful domain counts."""
        labels = tuple(running_labels)
        if labels:
            if len(labels) == 1:
                first = f"Update in progress: {labels[0]}"
            else:
                first = f"{len(labels)} updates in progress: {', '.join(labels)}"
            tooltip = f"{first}\nClick to watch it in the Procs tab."
            availability = UpdatesAvailableIndicator._availability_detail(
                count,
                core=core,
                agent_cli_count=agent_cli_count,
                manual_agent_cli_count=manual_agent_cli_count,
            )
            if availability:
                tooltip += f" {availability}"
            return tooltip
        if pending_restart is not None:
            tooltip = restart_pending_tooltip(pending_restart)
            availability = UpdatesAvailableIndicator._availability_detail(
                count,
                core=core,
                agent_cli_count=agent_cli_count,
                manual_agent_cli_count=manual_agent_cli_count,
            )
            if availability:
                tooltip += f" {availability}"
            return tooltip
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

    @staticmethod
    def _availability_detail(
        count: int,
        *,
        core: bool = False,
        agent_cli_count: int = 0,
        manual_agent_cli_count: int = 0,
    ) -> str:
        """Return the availability sentence without Updates-tab guidance."""
        if count <= 0 and agent_cli_count <= 0:
            return ""
        domains: list[str] = []
        if count > 0:
            noun = "update" if count == 1 else "updates"
            domains.append(f"{count} SASE/core/plugin {noun}")
        if agent_cli_count > 0:
            noun = "update" if agent_cli_count == 1 else "updates"
            domains.append(f"{agent_cli_count} agent CLI {noun}")
        detail = " and ".join(domains) + " available."
        if core:
            detail += " Includes sase-core (Rust rebuild, expect a slower update)."
        if manual_agent_cli_count > 0:
            noun = "update" if manual_agent_cli_count == 1 else "updates"
            detail += (
                f" {manual_agent_cli_count} agent CLI {noun} require"
                f"{'s' if manual_agent_cli_count == 1 else ''} manual action."
            )
        return detail
