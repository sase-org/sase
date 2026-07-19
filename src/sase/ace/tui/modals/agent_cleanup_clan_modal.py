"""Clan-scoped agent cleanup chooser for the ace TUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.agent_completion import status_style
from sase.ace.tui.agent_count_chip import format_agent_count_chip
from sase.core.agent_cleanup_facade import (
    agent_to_cleanup_target,
    agents_to_cleanup_targets,
    plan_agent_cleanup,
)
from sase.core.agent_cleanup_wire import (
    AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
    CLEANUP_MODE_KILL_AND_DISMISS,
    CLEANUP_SCOPE_CLAN,
    CLEANUP_SCOPE_CUSTOM_SELECTION,
    AgentCleanupIdentityWire,
    AgentCleanupPlanWire,
    AgentCleanupRequestWire,
)

from ..actions.agents._clan_cleanup import clan_members_for_container
from ..models._agent_clan import aggregate_clan_status, clan_member_counts
from ..models.agent_time import compute_row_runtime
from .agent_cleanup_types import (
    AgentCleanupAgentIdentity,
    AgentCleanupClanKey,
    AgentCleanupClanResult,
)
from .base import OptionListNavigationMixin

if TYPE_CHECKING:
    from ..models import Agent


@dataclass(frozen=True)
class _MemberRow:
    agent: Agent
    plan: AgentCleanupPlanWire


@dataclass(frozen=True)
class _ClanRow:
    key: AgentCleanupClanKey
    label: str
    container: Agent
    members: tuple[_MemberRow, ...]
    plan: AgentCleanupPlanWire


@dataclass(frozen=True)
class _VisibleRow:
    clan: _ClanRow
    member: _MemberRow | None = None

    @property
    def option_id(self) -> str:
        if self.member is None:
            return f"clan:{self.clan.label}:{self.clan.key[1] or ''}"
        identity = self.member.agent.identity
        return f"member:{identity[0].value}:{identity[1]}:{identity[2] or ''}"


class AgentCleanupClanModal(
    OptionListNavigationMixin, ModalScreen[AgentCleanupClanResult | None]
):
    """Choose whole clans or individual members with live planner previews."""

    _option_list_id = "agent-cleanup-clan-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("space", "toggle_row", "Toggle"),
        ("l", "expand", "Expand"),
        ("h", "collapse", "Collapse"),
        ("a", "toggle_all", "All"),
        ("enter", "confirm", "Clean Up"),
    ]

    def __init__(
        self,
        *,
        clans: list[Agent],
        targets: list[Agent],
        focused_panel_label: str,
        initial_clan: AgentCleanupClanKey | None = None,
    ) -> None:
        super().__init__()
        self._targets = list(targets)
        self._target_wires = agents_to_cleanup_targets(self._targets)
        self._focused_panel_label = focused_panel_label
        self._initial_clan = initial_clan
        self._rows = [self._build_clan_row(container) for container in clans]
        self._expanded: set[AgentCleanupClanKey] = set()
        self._selected_clans: set[AgentCleanupClanKey] = set()
        self._selected_members: set[AgentCleanupAgentIdentity] = set()
        self._visible_rows = self._build_visible_rows()
        self._programmatic_highlight = False

    def compose(self) -> ComposeResult:
        with Container(id="agent-cleanup-clan-container"):
            yield Label(
                f"Clan Cleanup — {self._focused_panel_label}",
                id="agent-cleanup-clan-title",
            )
            yield OptionList(
                *self._options(),
                id="agent-cleanup-clan-list",
            )
            yield Static(
                self._selection_summary(),
                id="agent-cleanup-clan-preview",
            )
            yield Static(
                "space toggle  l/h expand/collapse  a all  enter clean up  q close",
                id="agent-cleanup-clan-hints",
            )

    def on_mount(self) -> None:
        preferred = self._initial_option_id()
        self._restore_highlight(preferred)

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Suppress highlight echoes from modal-owned row rebuilds."""
        if self._programmatic_highlight:
            event.stop()

    def on_option_list_option_selected(self, _event: OptionList.OptionSelected) -> None:
        self.action_confirm()

    def action_toggle_row(self) -> None:
        visible = self._highlighted_row()
        if visible is None:
            return
        if visible.member is None:
            changed = self._toggle_clan(visible.clan)
        else:
            changed = self._toggle_member(visible.clan, visible.member)
        if changed:
            self._refresh_prompts()

    def action_toggle_all(self) -> None:
        enabled = {row.key for row in self._rows if self._clan_enabled(row)}
        if not enabled:
            self._set_preview("No clans have cleanup targets")
            return
        if enabled <= self._selected_clans:
            self._selected_clans -= enabled
            self._selected_members.clear()
        else:
            self._selected_clans = set(enabled)
            self._selected_members.clear()
        self._refresh_prompts()

    def action_expand(self) -> None:
        visible = self._highlighted_row()
        if visible is None:
            return
        clan = visible.clan
        if clan.key in self._expanded or not clan.members:
            return
        self._expanded.add(clan.key)
        self._rebuild_options(preferred=self._clan_option_id(clan))

    def action_collapse(self) -> None:
        visible = self._highlighted_row()
        if visible is None:
            return
        clan = visible.clan
        if clan.key not in self._expanded:
            return
        self._expanded.remove(clan.key)
        self._rebuild_options(preferred=self._clan_option_id(clan))

    def action_confirm(self) -> None:
        if not self._selected_clans and not self._selected_members:
            visible = self._highlighted_row()
            if visible is None or not self._clan_enabled(visible.clan):
                self._set_preview("Clan has no cleanup targets")
                return
            self.dismiss(
                AgentCleanupClanResult(clans=(visible.clan.key,), identities=())
            )
            return

        plan = self._selected_plan()
        if plan is None or not (plan.kill_items or plan.dismiss_items):
            self._set_preview("No selected agents can be cleaned up")
            return
        self.dismiss(
            AgentCleanupClanResult(
                clans=tuple(
                    row.key for row in self._rows if row.key in self._selected_clans
                ),
                identities=self._selected_member_identities_in_row_order(),
            )
        )

    def _build_clan_row(self, container: Agent) -> _ClanRow:
        key = self._clan_key(container)
        members = tuple(clan_members_for_container(container, self._targets))
        plan = self._plan_clan(container, members)
        member_rows = tuple(
            _MemberRow(agent=member, plan=self._plan_members((member,)))
            for member in members
        )
        return _ClanRow(
            key=key,
            label=key[0],
            container=container,
            members=member_rows,
            plan=plan,
        )

    def _plan_clan(
        self, container: Agent, members: tuple[Agent, ...]
    ) -> AgentCleanupPlanWire:
        if container.agent_clan:
            request = AgentCleanupRequestWire(
                schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
                scope=CLEANUP_SCOPE_CLAN,
                mode=CLEANUP_MODE_KILL_AND_DISMISS,
                clan_name=container.agent_clan,
                clan_generation=container.agent_clan_generation,
                include_pidless_as_dismissable=True,
            )
            return plan_agent_cleanup(self._target_wires, request)
        return self._plan_members(members)

    def _plan_members(self, members: tuple[Agent, ...]) -> AgentCleanupPlanWire:
        request = AgentCleanupRequestWire(
            schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
            scope=CLEANUP_SCOPE_CUSTOM_SELECTION,
            mode=CLEANUP_MODE_KILL_AND_DISMISS,
            identities=tuple(
                agent_to_cleanup_target(member).identity for member in members
            ),
            include_pidless_as_dismissable=True,
        )
        return plan_agent_cleanup(self._target_wires, request)

    def _selected_plan(self) -> AgentCleanupPlanWire | None:
        identities = self._selected_wire_identities()
        if not identities:
            return None
        request = AgentCleanupRequestWire(
            schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
            scope=CLEANUP_SCOPE_CUSTOM_SELECTION,
            mode=CLEANUP_MODE_KILL_AND_DISMISS,
            identities=identities,
            include_pidless_as_dismissable=True,
        )
        return plan_agent_cleanup(self._target_wires, request)

    def _selected_wire_identities(self) -> tuple[AgentCleanupIdentityWire, ...]:
        seen: set[AgentCleanupIdentityWire] = set()
        identities: list[AgentCleanupIdentityWire] = []
        for row in self._rows:
            if row.key in self._selected_clans:
                candidates = row.plan.selected_identities
            else:
                candidates = tuple(
                    member.plan.selected_identities[0]
                    for member in row.members
                    if member.agent.identity in self._selected_members
                    and member.plan.selected_identities
                )
            for identity in candidates:
                if identity in seen:
                    continue
                seen.add(identity)
                identities.append(identity)
        return tuple(identities)

    def _toggle_clan(self, row: _ClanRow) -> bool:
        if not self._clan_enabled(row):
            self._set_preview("Clan has no cleanup targets")
            return False
        member_ids = {member.agent.identity for member in row.members}
        if row.key in self._selected_clans:
            self._selected_clans.remove(row.key)
            self._selected_members -= member_ids
        else:
            self._selected_clans.add(row.key)
            self._selected_members -= member_ids
        return True

    def _toggle_member(self, clan: _ClanRow, member: _MemberRow) -> bool:
        if not self._member_enabled(member):
            self._set_preview("Member has no cleanup target")
            return False
        enabled_ids = {
            row.agent.identity for row in clan.members if self._member_enabled(row)
        }
        if clan.key in self._selected_clans:
            self._selected_clans.remove(clan.key)
            self._selected_members |= enabled_ids
        identity = member.agent.identity
        if identity in self._selected_members:
            self._selected_members.remove(identity)
        else:
            self._selected_members.add(identity)
        return True

    def _build_visible_rows(self) -> list[_VisibleRow]:
        visible: list[_VisibleRow] = []
        for clan in self._rows:
            visible.append(_VisibleRow(clan=clan))
            if clan.key in self._expanded:
                visible.extend(
                    _VisibleRow(clan=clan, member=member) for member in clan.members
                )
        return visible

    def _options(self) -> list[Option]:
        options: list[Option] = []
        for visible in self._visible_rows:
            if visible.member is None:
                prompt = self._clan_row_label(visible.clan)
                enabled = self._clan_enabled(visible.clan)
            else:
                prompt = self._member_row_label(visible.clan, visible.member)
                enabled = self._member_enabled(visible.member)
            options.append(Option(prompt, id=visible.option_id, disabled=not enabled))
        return options

    def _clan_row_label(self, row: _ClanRow) -> Text:
        enabled = self._clan_enabled(row)
        marker = self._clan_marker(row)
        text = Text()
        marker_style = "bold #00D7AF" if marker != "○" else "dim"
        text.append(f"{marker} ", style=marker_style if enabled else "dim")
        text.append(row.label, style="bold cyan" if enabled else "dim")
        status = (
            aggregate_clan_status(member.agent.status for member in row.members)
            or row.container.display_status
        )
        text.append(f"  {status}", style=status_style(status) if enabled else "dim")
        counts = clan_member_counts(row.container)
        chip = format_agent_count_chip(
            stopped=counts.awaiting,
            running=counts.running,
            waiting=counts.waiting,
            failed=counts.failed,
            unread=counts.unread,
            done=counts.done,
        )
        if chip:
            text.append(" ")
            text.append_text(chip)
        plan_counts = row.plan.counts
        member_label = "member" if len(row.members) == 1 else "members"
        text.append(
            f"\n   {len(row.members)} {member_label} · "
            f"kill {plan_counts.kill} · dismiss {plan_counts.dismiss}",
            style="dim" if enabled else "dim italic",
        )
        if plan_counts.cascaded_workflow_children:
            text.append(
                f" · cascade {plan_counts.cascaded_workflow_children}",
                style="dim magenta" if enabled else "dim italic",
            )
        return text

    def _member_row_label(self, clan: _ClanRow, member: _MemberRow) -> Text:
        enabled = self._member_enabled(member)
        selected = (
            clan.key in self._selected_clans
            or member.agent.identity in self._selected_members
        )
        text = Text()
        text.append(
            "    ● " if selected else "    ○ ", style="cyan" if selected else "dim"
        )
        text.append(
            self._relative_member_label(member.agent, clan.label),
            style="bold" if enabled else "dim",
        )
        text.append(
            f"  {member.agent.display_status}",
            style=status_style(member.agent.display_status) if enabled else "dim",
        )
        _timestamp, runtime = compute_row_runtime(member.agent)
        if runtime:
            text.append(f"  {runtime}", style="dim")
        return text

    def _clan_marker(self, row: _ClanRow) -> str:
        if row.key in self._selected_clans:
            return "●"
        enabled_ids = {
            member.agent.identity
            for member in row.members
            if self._member_enabled(member)
        }
        selected = enabled_ids & self._selected_members
        if not selected:
            return "○"
        if selected == enabled_ids:
            return "●"
        return "◐"

    @staticmethod
    def _clan_enabled(row: _ClanRow) -> bool:
        return bool(row.plan.kill_items or row.plan.dismiss_items)

    @staticmethod
    def _member_enabled(row: _MemberRow) -> bool:
        return bool(row.plan.kill_items or row.plan.dismiss_items)

    def _selection_summary(self) -> Text:
        plan = self._selected_plan()
        clan_count = len(self._selected_clans)
        member_count = len(self._selected_members)
        text = Text("Selected: ", style="dim")
        if not clan_count and not member_count:
            text.append("none", style="dim italic")
            return text
        parts: list[str] = []
        if clan_count:
            parts.append(f"{clan_count} clan{'s' if clan_count != 1 else ''}")
        if member_count:
            parts.append(f"{member_count} member{'s' if member_count != 1 else ''}")
        text.append(" + ".join(parts), style="bold cyan")
        if plan is not None:
            counts = plan.counts
            text.append(f" → kill {counts.kill}", style="yellow")
            text.append(f" · dismiss {counts.dismiss}", style="green")
            if counts.cascaded_workflow_children:
                text.append(
                    f" · cascade {counts.cascaded_workflow_children}",
                    style="magenta",
                )
        return text

    def _refresh_prompts(self) -> None:
        try:
            option_list = self.query_one("#agent-cleanup-clan-list", OptionList)
            for index, option in enumerate(self._options()):
                option_list.replace_option_prompt_at_index(index, option.prompt)
            self.query_one("#agent-cleanup-clan-preview", Static).update(
                self._selection_summary()
            )
        except Exception:
            pass

    def _rebuild_options(self, *, preferred: str | None) -> None:
        self._visible_rows = self._build_visible_rows()
        try:
            option_list = self.query_one("#agent-cleanup-clan-list", OptionList)
        except Exception:
            return
        self._programmatic_highlight = True
        try:
            option_list.clear_options()
            option_list.add_options(self._options())
            self._restore_highlight(preferred, option_list=option_list)
        finally:
            self._programmatic_highlight = False
        self._set_preview(self._selection_summary())

    def _restore_highlight(
        self, preferred: str | None, *, option_list: OptionList | None = None
    ) -> None:
        target = option_list or self.query_one("#agent-cleanup-clan-list", OptionList)
        previous_guard = self._programmatic_highlight
        self._programmatic_highlight = True
        try:
            index: int | None = None
            if preferred:
                try:
                    index = target.get_option_index(preferred)
                except Exception:
                    index = None
            if index is None:
                index = self._first_enabled_index()
            target.highlighted = index
        finally:
            self._programmatic_highlight = previous_guard

    def _initial_option_id(self) -> str | None:
        if self._initial_clan is not None:
            for row in self._rows:
                if row.key == self._initial_clan and self._clan_enabled(row):
                    return self._clan_option_id(row)
        for row in self._rows:
            if self._clan_enabled(row):
                return self._clan_option_id(row)
        return None

    def _first_enabled_index(self) -> int | None:
        for index, visible in enumerate(self._visible_rows):
            if visible.member is None and self._clan_enabled(visible.clan):
                return index
            if visible.member is not None and self._member_enabled(visible.member):
                return index
        return None

    def _highlighted_row(self) -> _VisibleRow | None:
        try:
            option_list = self.query_one("#agent-cleanup-clan-list", OptionList)
        except Exception:
            return None
        highlighted = option_list.highlighted
        if highlighted is None or not 0 <= highlighted < len(self._visible_rows):
            return None
        return self._visible_rows[highlighted]

    def _selected_member_identities_in_row_order(
        self,
    ) -> tuple[AgentCleanupAgentIdentity, ...]:
        return tuple(
            member.agent.identity
            for row in self._rows
            for member in row.members
            if member.agent.identity in self._selected_members
        )

    def _set_preview(self, content: str | Text) -> None:
        try:
            self.query_one("#agent-cleanup-clan-preview", Static).update(content)
        except Exception:
            pass

    @staticmethod
    def _clan_key(container: Agent) -> AgentCleanupClanKey:
        label = container.agent_clan or container.agent_name or container.display_name
        generation = (
            container.agent_clan_generation
            if container.agent_clan
            else container.raw_suffix
        )
        return (label, generation)

    @staticmethod
    def _clan_option_id(row: _ClanRow) -> str:
        return _VisibleRow(clan=row).option_id

    @staticmethod
    def _relative_member_label(member: Agent, clan_name: str) -> str:
        name = member.agent_name or member.step_name or member.display_name
        prefix = f"{clan_name}."
        return name[len(clan_name) :] if name.startswith(prefix) else name


__all__ = ["AgentCleanupClanModal"]
