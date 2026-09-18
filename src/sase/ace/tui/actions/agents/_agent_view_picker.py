"""Agents-tab detail view picker action."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from ...llm_calls import supports_slow_tool_sources
from ...widgets._agent_detail_panels import (
    DetailLayoutMode,
    DetailPanelMode,
    next_detail_layout_mode,
)
from ._panel_types import TabName

if TYPE_CHECKING:
    from ...models import Agent
    from ...widgets import AgentDetail
    from ...modals.agent_view_modal import AgentViewChoice, AgentViewResult


@dataclass(frozen=True)
class _AgentViewOpenSnapshot:
    """Selection identity captured when the picker opens."""

    tab: TabName
    agent_identity: tuple[object, ...]
    attempt_number: int | None
    forced_metadata_reason: str | None


@dataclass(frozen=True)
class _AgentViewCapabilities:
    """Current presentation-only capability state for the picker."""

    agent: Agent
    forced_metadata_reason: str | None
    file_enabled: bool
    file_subtitle: str
    llm_calls_enabled: bool
    llm_calls_reason: str | None
    layout_enabled: bool
    layout_reason: str | None
    secondary_label: str
    current_mode: DetailPanelMode
    effective_layout: DetailLayoutMode


class AgentViewPickerMixin:
    """Open and apply the Agents detail view/layout picker."""

    current_tab: TabName
    current_attempt_number: int | None

    def _agent_view_picker_busy_reason(self) -> str | None:
        """Return why modal-like or prefix state currently owns input."""
        from textual.screen import ModalScreen

        if isinstance(getattr(self, "screen", None), ModalScreen):
            return "Finish the current modal first"
        prompt_active = getattr(self, "_prompt_input_active", None)
        if callable(prompt_active) and prompt_active():
            return "Finish the prompt first"
        if getattr(self, "_agents_filter_session_open", False):
            return "Finish the query first"
        metadata_search = getattr(self, "_agent_metadata_search", None)
        if bool(getattr(metadata_search, "is_active", False)):
            return "Finish metadata search first"
        for attr in (
            "_leader_mode_active",
            "_bang_mode_active",
            "_fold_mode_active",
            "_copy_mode_active",
            "_entry_jump_mode_active",
            "_panel_fold_hint_mode_active",
        ):
            if getattr(self, attr, False):
                return "Finish the active key mode first"
        if getattr(self, "_custom_mode_active", None) is not None:
            return "Finish the active key mode first"
        if getattr(self, "_member_jump_pending_digit", None):
            return "Finish member jump first"
        return None

    def _agent_view_picker_block_reason(self) -> str | None:
        """Return why the Agent view picker cannot open right now."""
        if self.current_tab != "agents":
            return "Agent view is only available on the Agents tab"
        busy_reason = self._agent_view_picker_busy_reason()
        if busy_reason is not None:
            return busy_reason
        resolve_panel = getattr(self, "_resolve_focused_panel", None)
        if callable(resolve_panel) and resolve_panel() is not None:
            return "Select an agent row first"
        if getattr(self, "_current_group_key", None) is not None:
            return "Select an agent row first"
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            return "No agent selected"
        return None

    def _can_open_agent_view_picker(self) -> bool:
        """Return whether the Agent view picker is currently applicable."""
        return self._agent_view_picker_block_reason() is None

    def action_choose_agent_view(self) -> None:
        """Open the Agents detail view/layout picker."""
        reason = self._agent_view_picker_block_reason()
        if reason is not None:
            if self.current_tab == "agents":
                self.notify(reason, severity="warning", timeout=3.0)  # type: ignore[attr-defined]
            return

        from ...modals.agent_view_modal import AgentViewModal
        from ...widgets import AgentDetail

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning", timeout=3.0)  # type: ignore[attr-defined]
            return
        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        capabilities = self._agent_view_capabilities(agent_detail, agent)
        snapshot = _AgentViewOpenSnapshot(
            tab=self.current_tab,
            agent_identity=agent.identity,
            attempt_number=getattr(self, "current_attempt_number", None),
            forced_metadata_reason=capabilities.forced_metadata_reason,
        )
        choices = self._agent_view_choices(agent_detail, capabilities)
        selected_key = self._agent_view_selected_key(capabilities)

        def _on_choice(result: AgentViewResult | None) -> None:
            if result is None:
                return
            self._apply_agent_view_result(snapshot, result)

        self.push_screen(  # type: ignore[attr-defined]
            AgentViewModal(choices, selected_key=selected_key),
            _on_choice,
        )

    def _agent_view_capabilities(
        self,
        agent_detail: AgentDetail,
        agent: Agent,
    ) -> _AgentViewCapabilities:
        forced_reason = self._forced_metadata_reason(agent)
        current_mode = (
            DetailPanelMode.LLM_CALLS
            if agent_detail.panel_mode is DetailPanelMode.LLM_CALLS
            else DetailPanelMode.AUTO
        )
        file_enabled = forced_reason is None
        file_has_content = bool(getattr(agent_detail, "_has_file_content", False))
        file_subtitle = (
            "Files and diffs"
            if file_has_content
            else "No file currently; metadata fills the space"
        )
        llm_calls_enabled = forced_reason is None and supports_slow_tool_sources(agent)
        llm_calls_reason: str | None = None
        if forced_reason is not None:
            llm_calls_reason = forced_reason
        elif not llm_calls_enabled:
            llm_calls_reason = "Unavailable for this entry"

        secondary_label = "File / LLM Calls"
        layout_enabled = False
        layout_reason: str | None = "Choose File or LLM Calls first"
        if forced_reason is not None:
            layout_reason = forced_reason
        elif current_mode == DetailPanelMode.LLM_CALLS:
            secondary_label = "LLM Calls"
            llm_calls_has_content = bool(
                getattr(agent_detail, "_has_llm_calls_content", False)
            )
            layout_enabled = llm_calls_enabled and llm_calls_has_content
            layout_reason = None if layout_enabled else "No LLM Calls to resize"
        else:
            secondary_label = "File"
            layout_enabled = file_has_content
            layout_reason = None if layout_enabled else "No file to resize"

        saved_layout = agent_detail.detail_layout_mode
        effective_layout = saved_layout
        if forced_reason is not None or not layout_enabled:
            effective_layout = DetailLayoutMode.METADATA_ONLY

        return _AgentViewCapabilities(
            agent=agent,
            forced_metadata_reason=forced_reason,
            file_enabled=file_enabled,
            file_subtitle=file_subtitle,
            llm_calls_enabled=llm_calls_enabled,
            llm_calls_reason=llm_calls_reason,
            layout_enabled=layout_enabled,
            layout_reason=layout_reason,
            secondary_label=secondary_label,
            current_mode=current_mode,
            effective_layout=effective_layout,
        )

    def _forced_metadata_reason(self, agent: Agent) -> str | None:
        if getattr(self, "current_attempt_number", None) is not None:
            return "Historical attempt"
        if getattr(agent, "is_clan_container", False) or getattr(
            agent, "is_proc_shell", False
        ):
            return "Summary view"
        return None

    def _agent_view_choices(
        self,
        agent_detail: AgentDetail,
        capabilities: _AgentViewCapabilities,
    ) -> tuple[AgentViewChoice, ...]:
        from ...modals.agent_view_modal import AgentViewChoice, AgentViewResult

        current_mode = capabilities.current_mode
        forced_reason = capabilities.forced_metadata_reason
        choices: list[AgentViewChoice] = [
            AgentViewChoice(
                "f",
                "File",
                capabilities.file_subtitle,
                "view",
                AgentViewResult.mode_choice(DetailPanelMode.AUTO),
                enabled=capabilities.file_enabled,
                badge="Current" if current_mode is DetailPanelMode.AUTO else None,
                disabled_reason=forced_reason,
            ),
            AgentViewChoice(
                "t",
                "LLM Calls",
                "Provider tool calls and activity",
                "view",
                AgentViewResult.mode_choice(DetailPanelMode.LLM_CALLS),
                enabled=capabilities.llm_calls_enabled,
                badge="Current" if current_mode is DetailPanelMode.LLM_CALLS else None,
                disabled_reason=capabilities.llm_calls_reason,
            ),
        ]

        saved_layout = agent_detail.detail_layout_mode
        secondary_label = capabilities.secondary_label
        if current_mode == DetailPanelMode.AUTO:
            secondary_label = "File"
        elif current_mode == DetailPanelMode.LLM_CALLS:
            secondary_label = "LLM Calls"
        next_layout = next_detail_layout_mode(saved_layout, direction=1)
        previous_layout = next_detail_layout_mode(saved_layout, direction=-1)

        def layout_badge(
            layout: DetailLayoutMode,
        ) -> Literal["Current", "Saved"] | None:
            if capabilities.effective_layout is layout:
                return "Current"
            if saved_layout is layout:
                return "Saved"
            return None

        choices.extend(
            [
                AgentViewChoice(
                    "[",
                    "Metadata only",
                    "Metadata fills the detail area",
                    "layout",
                    AgentViewResult.layout_choice(DetailLayoutMode.METADATA_ONLY),
                    enabled=True,
                    badge=layout_badge(DetailLayoutMode.METADATA_ONLY),
                ),
                AgentViewChoice(
                    "1",
                    "Metadata larger",
                    f"Metadata 70% / {secondary_label} 30%",
                    "layout",
                    AgentViewResult.layout_choice(DetailLayoutMode.METADATA_LARGER),
                    enabled=capabilities.layout_enabled,
                    badge=layout_badge(DetailLayoutMode.METADATA_LARGER),
                    disabled_reason=capabilities.layout_reason,
                ),
                AgentViewChoice(
                    "=",
                    "Equal split",
                    f"Metadata 50% / {secondary_label} 50%",
                    "layout",
                    AgentViewResult.layout_choice(DetailLayoutMode.EQUAL),
                    enabled=capabilities.layout_enabled,
                    badge=layout_badge(DetailLayoutMode.EQUAL),
                    disabled_reason=capabilities.layout_reason,
                ),
                AgentViewChoice(
                    "2",
                    f"{secondary_label} larger",
                    f"Metadata 30% / {secondary_label} 70%",
                    "layout",
                    AgentViewResult.layout_choice(DetailLayoutMode.SECONDARY_LARGER),
                    enabled=capabilities.layout_enabled,
                    badge=layout_badge(DetailLayoutMode.SECONDARY_LARGER),
                    disabled_reason=capabilities.layout_reason,
                ),
                AgentViewChoice(
                    "]",
                    f"{secondary_label} only",
                    f"{secondary_label} fills the detail area",
                    "layout",
                    AgentViewResult.layout_choice(DetailLayoutMode.SECONDARY_ONLY),
                    enabled=capabilities.layout_enabled,
                    badge=layout_badge(DetailLayoutMode.SECONDARY_ONLY),
                    disabled_reason=capabilities.layout_reason,
                ),
                AgentViewChoice(
                    "p",
                    "Next layout",
                    self._agent_view_cycle_subtitle(
                        saved_layout, next_layout, secondary_label
                    ),
                    "layout",
                    AgentViewResult.cycle(1),
                    enabled=capabilities.layout_enabled,
                    disabled_reason=capabilities.layout_reason,
                ),
                AgentViewChoice(
                    "P",
                    "Previous layout",
                    self._agent_view_cycle_subtitle(
                        saved_layout, previous_layout, secondary_label
                    ),
                    "layout",
                    AgentViewResult.cycle(-1),
                    enabled=capabilities.layout_enabled,
                    disabled_reason=capabilities.layout_reason,
                ),
            ]
        )
        return tuple(choices)

    def _agent_view_cycle_subtitle(
        self,
        old_layout: DetailLayoutMode,
        new_layout: DetailLayoutMode,
        secondary_label: str,
    ) -> str:
        return (
            f"{self._agent_view_layout_name(old_layout, secondary_label)} -> "
            f"{self._agent_view_layout_name(new_layout, secondary_label)}"
        )

    def _agent_view_layout_name(
        self,
        layout: DetailLayoutMode,
        secondary_label: str,
    ) -> str:
        if layout is DetailLayoutMode.METADATA_LARGER:
            return "Metadata larger"
        if layout is DetailLayoutMode.EQUAL:
            return "Equal split"
        if layout is DetailLayoutMode.SECONDARY_LARGER:
            return f"{secondary_label} larger"
        if layout is DetailLayoutMode.SECONDARY_ONLY:
            return f"{secondary_label} only"
        return "Metadata only"

    def _agent_view_selected_key(self, capabilities: _AgentViewCapabilities) -> str:
        if capabilities.effective_layout is DetailLayoutMode.METADATA_ONLY:
            return "["
        if capabilities.effective_layout is DetailLayoutMode.SECONDARY_ONLY:
            return "]"
        if capabilities.current_mode is DetailPanelMode.LLM_CALLS:
            return "t"
        return "f"

    def _apply_agent_view_result(
        self,
        snapshot: _AgentViewOpenSnapshot,
        result: AgentViewResult,
    ) -> None:
        if self.current_tab != snapshot.tab:
            self.notify("Selection changed; reopen Agent view", severity="warning")  # type: ignore[attr-defined]
            return

        from ...widgets import AgentDetail

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if (
            agent is None
            or agent.identity != snapshot.agent_identity
            or getattr(self, "current_attempt_number", None) != snapshot.attempt_number
        ):
            self.notify("Selection changed; reopen Agent view", severity="warning")  # type: ignore[attr-defined]
            return

        agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        capabilities = self._agent_view_capabilities(agent_detail, agent)
        if capabilities.forced_metadata_reason != snapshot.forced_metadata_reason:
            self.notify("Selection changed; reopen Agent view", severity="warning")  # type: ignore[attr-defined]
            return

        if result.kind == "mode":
            self._apply_agent_view_mode_result(agent_detail, capabilities, result)
        elif result.kind == "layout":
            self._apply_agent_layout_result(agent_detail, capabilities, result)
        elif result.kind == "cycle":
            self._apply_agent_layout_cycle(agent_detail, capabilities, result)

    def _apply_agent_view_mode_result(
        self,
        agent_detail: AgentDetail,
        capabilities: _AgentViewCapabilities,
        result: AgentViewResult,
    ) -> None:
        mode = result.mode
        if mode is None:
            return
        reason = self._mode_rejection_reason(capabilities, mode)
        if reason is not None:
            self.notify(reason, severity="warning")  # type: ignore[attr-defined]
            return
        if capabilities.forced_metadata_reason is not None:
            return
        changed = agent_detail.set_panel_mode(
            mode,
            capabilities.agent,
            attempt_number=getattr(self, "current_attempt_number", None),
        )
        if changed:
            self._refresh_agent_view_surfaces()

    def _mode_rejection_reason(
        self,
        capabilities: _AgentViewCapabilities,
        mode: DetailPanelMode,
    ) -> str | None:
        if capabilities.forced_metadata_reason is not None:
            return (
                None
                if mode is DetailPanelMode.INFO
                else capabilities.forced_metadata_reason
            )
        if mode is DetailPanelMode.LLM_CALLS and not capabilities.llm_calls_enabled:
            return capabilities.llm_calls_reason or "Unavailable for this entry"
        if mode is DetailPanelMode.AUTO and not capabilities.file_enabled:
            return capabilities.forced_metadata_reason
        return None

    def _apply_agent_layout_result(
        self,
        agent_detail: AgentDetail,
        capabilities: _AgentViewCapabilities,
        result: AgentViewResult,
    ) -> None:
        layout = result.layout
        if layout is None:
            return
        if (
            capabilities.forced_metadata_reason is not None
            and layout is DetailLayoutMode.METADATA_ONLY
        ):
            return
        if (
            layout is not DetailLayoutMode.METADATA_ONLY
            and not capabilities.layout_enabled
        ):
            self.notify(  # type: ignore[attr-defined]
                capabilities.layout_reason or "Choose File or LLM Calls first",
                severity="warning",
            )
            return
        if agent_detail.detail_layout_mode is layout:
            return
        agent_detail.set_detail_layout(layout)
        self._refresh_agent_view_surfaces()

    def _apply_agent_layout_cycle(
        self,
        agent_detail: AgentDetail,
        capabilities: _AgentViewCapabilities,
        result: AgentViewResult,
    ) -> None:
        if not capabilities.layout_enabled:
            self.notify(  # type: ignore[attr-defined]
                capabilities.layout_reason or "Choose File or LLM Calls first",
                severity="warning",
            )
            return
        direction = result.cycle_direction
        if direction is None:
            return
        if agent_detail.cycle_detail_layout(direction=direction):
            self._refresh_agent_view_surfaces()

    def _refresh_agent_view_surfaces(self) -> None:
        update_info = getattr(self, "_update_agents_info_panel", None)
        if callable(update_info):
            update_info()
        refresh_footer = getattr(self, "_refresh_agent_footer_bindings_only", None)
        if callable(refresh_footer):
            refresh_footer()


__all__ = ["AgentViewPickerMixin"]
