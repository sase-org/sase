"""Agents-tab ingress for the durable Agent Hijack stop protocol."""

from __future__ import annotations

import asyncio
import logging
import shlex
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from ._hijack_decision import (
    HijackDecisionView,
    agent_can_offer_hijack,
    agent_hijack_ingress_available,
    format_hijack_decision_toast,
)
from ._hijack_decision_cache import AgentHijackDecisionCacheMixin

if TYPE_CHECKING:
    from ...models import Agent

log = logging.getLogger(__name__)


class AgentHijackActionMixin(AgentHijackDecisionCacheMixin):
    """Submit eligible hijacks, run non-destructive redirects, and toast reasons."""

    def _start_hijack_agent(self, agent: Agent | None = None) -> bool:
        """Start the durable stop protocol for *agent* or the selected row."""
        explicit = agent is not None
        if agent is None:
            getter = getattr(self, "_get_selected_agent", None)
            agent = getter() if callable(getter) else None
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return False
        view = self._cached_hijack_decision(agent)
        if view is not None:
            return self._act_on_hijack_decision(
                agent, view, require_selected=not explicit
            )
        acted: list[bool] = []

        def _then(decided: HijackDecisionView) -> None:
            acted.append(
                self._act_on_hijack_decision(
                    agent,
                    decided,
                    require_selected=not explicit,
                )
            )

        self._schedule_hijack_decision(agent, then=_then)
        return acted[0] if acted else True

    def _act_on_hijack_decision(
        self,
        agent: Agent,
        view: HijackDecisionView,
        *,
        require_selected: bool = True,
    ) -> bool:
        """Apply one cached backend decision on the UI thread."""
        current = self._hijack_row_for_identity(agent.identity) or agent
        if require_selected:
            getter = getattr(self, "_get_selected_agent", None)
            selected = getter() if callable(getter) else current
            if selected is None or selected.identity != current.identity:
                return False
        mode = view.mode
        if mode == "refused":
            self._toast_hijack_decision(view.decision)
            return False
        if mode == "redirect":
            return self._perform_hijack_redirect(current, view)
        if mode in {"immediate", "latched"}:
            return self._submit_occupying_hijack(current, view)
        self._toast_hijack_decision(view.decision)
        return False

    def _submit_occupying_hijack(self, agent: Agent, view: HijackDecisionView) -> bool:
        """Submit the stop protocol for the occupying member."""
        occupant = self._hijack_row_for_name(view.occupant_name) or agent
        name = view.occupant_name or occupant.agent_name
        if not isinstance(name, str) or not name:
            self.notify("Selected row has no local agent name", severity="error")  # type: ignore[attr-defined]
            return False
        if (
            occupant.hijack_overlay == "hijacking"
            or agent.hijack_overlay == "hijacking"
        ):
            self.notify("Hijack is already running for this agent")  # type: ignore[attr-defined]
            return False

        from ..agent_durable import submit_agent_hijack

        occupant.hijack_overlay = "hijacking"
        if agent.identity != occupant.identity:
            agent.hijack_overlay = "hijacking"
        self._refresh_hijack_row(occupant)
        if agent.identity != occupant.identity:
            self._refresh_hijack_row(agent)

        def on_complete(completion: Any) -> None:
            current = self._hijack_row_for_identity(occupant.identity) or occupant
            selected = self._hijack_row_for_identity(agent.identity) or agent
            current.hijack_overlay = None
            if selected.identity != current.identity:
                selected.hijack_overlay = None
            payload = completion.payload
            status = payload.get("status") if isinstance(payload, dict) else None
            current.hijack_stop_failed = status == "stop_failed"
            if status == "held":
                current.hijack_stop_failed = False
            self._refresh_hijack_row(current)
            if selected.identity != current.identity:
                self._refresh_hijack_row(selected)
            severity = payload.get("severity") if isinstance(payload, dict) else None
            if severity not in {"warning", "error"}:
                severity = "information" if completion.success else "warning"
            if completion.message:
                self.notify(completion.message, severity=severity)  # type: ignore[attr-defined]
            refresh_source = (
                payload.get("schedule_agents_refresh_source")
                if isinstance(payload, dict)
                else None
            )
            if isinstance(refresh_source, str):
                refresh = getattr(self, "_schedule_agents_async_refresh", None)
                if callable(refresh):
                    refresh(source=refresh_source)

        session_name = _hijack_session_name(occupant) or _hijack_session_name(agent)
        submitted = submit_agent_hijack(
            self,
            name=name,
            identity=str(occupant.identity),
            cl_name=occupant.cl_name,
            project_file=occupant.project_file,
            display_name=f"Hijack {occupant.display_name}",
            session_name=session_name,
            on_complete=on_complete,
        )
        if not submitted:
            occupant.hijack_overlay = None
            if agent.identity != occupant.identity:
                agent.hijack_overlay = None
            self._refresh_hijack_row(occupant)
            self.notify("Could not queue the hijack operation", severity="error")  # type: ignore[attr-defined]
        return submitted

    def _perform_hijack_redirect(self, agent: Agent, view: HijackDecisionView) -> bool:
        """Run a non-destructive navigation the backend asked the TUI to perform."""
        op = view.redirect_op
        if op == "copy_remote_command":
            return self._copy_remote_hijack_command(agent)
        if op == "open_recovery":
            return self._redirect_open_recovery(agent, view)
        if op == "gate_review":
            return self._redirect_gate_review(agent, view)
        if op == "select_member":
            return self._redirect_select_member(agent, view)
        if op == "show_active_hijack":
            self._toast_hijack_decision(view.decision)
            return True
        self._toast_hijack_decision(view.decision)
        return True

    def _redirect_open_recovery(self, agent: Agent, view: HijackDecisionView) -> bool:
        occupant = self._hijack_row_for_name(view.occupant_name) or agent
        from ._remote_lifecycle import is_remote_fleet_agent

        if is_remote_fleet_agent(occupant):
            return self._copy_remote_hijack_command(occupant)
        from ._hijack_recovery_panel import open_hijack_recovery_panel

        open_hijack_recovery_panel(self, occupant)
        return True

    def _redirect_gate_review(self, agent: Agent, view: HijackDecisionView) -> bool:
        occupant = self._hijack_row_for_name(view.occupant_name) or agent
        resolver = getattr(self, "_agent_enter_resolution", None)
        dispatcher = getattr(self, "_dispatch_agent_enter_resolution", None)
        if not callable(resolver) or not callable(dispatcher):
            self._toast_hijack_decision(view.decision)
            return True
        resolution = resolver(occupant)
        gate_targets = tuple(
            target for target in resolution.targets if target.kind == "gate"
        )
        if not gate_targets:
            self._toast_hijack_decision(view.decision)
            return True
        dispatcher(occupant, replace(resolution, targets=gate_targets))
        return True

    def _redirect_select_member(self, agent: Agent, view: HijackDecisionView) -> bool:
        from ._clan_cleanup import clan_members_for_container

        members = clan_members_for_container(
            agent, getattr(self, "_agents_with_children", [])
        )
        live = [member for member in members if _cheap_live_member(member)]
        if len(live) == 1 and live[0].identity != agent.identity:
            member = live[0]
            self._select_hijack_retarget(member)
            return self._start_hijack_agent(member)
        self._toast_hijack_decision(view.decision)
        return True

    def _select_hijack_retarget(self, member: Agent) -> None:
        """Move list selection onto *member* when that row is visible."""
        agents = getattr(self, "_agents", ())
        for index, row in enumerate(agents):
            if row.identity == member.identity:
                self.current_idx = index  # type: ignore[attr-defined]
                refresh = getattr(self, "_refresh_agents_display", None)
                if callable(refresh):
                    refresh(list_changed=False, defer_detail=True)
                return

    def _copy_remote_hijack_command(self, agent: Agent) -> bool:
        """Guide the operator to run the hijack on a remote row's host."""
        alias = str(agent.fleet_origin_alias or "remote")
        name = agent.agent_name
        if not isinstance(name, str) or not name:
            self.notify("Remote row has no agent name", severity="warning")  # type: ignore[attr-defined]
            return False
        command = f"sase agent hijack {shlex.quote(name)}"
        from ..clipboard import schedule_copy_delivery

        schedule_copy_delivery(
            self,
            command,
            copied_label=f"hijack command for {alias}",
            task_name=f"copy-hijack-command-{alias}",
            on_failure="toast",
        )
        self._record_remote_hijack_referral(alias, name)
        self.notify(f"Agent runs on {alias}; copied: {command}")  # type: ignore[attr-defined]
        return True

    def _record_remote_hijack_referral(self, alias: str, name: str) -> None:
        """Persist the copied remote request off the UI thread when possible."""

        def _write() -> None:
            try:
                from sase.agent.hijack.referral import record_remote_hijack_referral

                record_remote_hijack_referral(alias, name)
            except Exception:
                log.warning(
                    "failed to record remote hijack referral alias=%s agent=%s",
                    alias,
                    name,
                    exc_info=True,
                )

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            _write()
            return
        from ...util.pump_tasks import spawn_pump_free_task

        spawn_pump_free_task(
            self,
            asyncio.to_thread(_write),
            name=f"hijack-referral-{alias}",
            registry_attr="_pump_free_hijack_referral_tasks",
        )

    def _toast_hijack_decision(self, decision: dict[str, Any]) -> None:
        message = format_hijack_decision_toast(decision)
        if decision.get("mode") == "refused":
            code = decision.get("code")
            log.info(
                "agent_hijack_tui_refused code=%s mode=%s",
                code if isinstance(code, str) and code else "-",
                decision.get("mode") or "unknown",
            )
        self.notify(message, severity="warning")  # type: ignore[attr-defined]

    def _hijack_row_for_name(self, name: str | None) -> Agent | None:
        if not isinstance(name, str) or not name:
            return None
        for row in getattr(self, "_agents_with_children", ()):
            if row.agent_name == name:
                return row
        for row in getattr(self, "_agents", ()):
            if row.agent_name == name:
                return row
        return None

    def _hijack_row_for_identity(self, identity: tuple[object, ...]) -> Agent | None:
        resolver = getattr(self, "_agent_by_identity", None)
        if callable(resolver):
            found = resolver(identity)
            if found is not None:
                return found
        for row in getattr(self, "_agents_with_children", ()):
            if row.identity == identity:
                return row
        for row in getattr(self, "_agents", ()):
            if row.identity == identity:
                return row
        return None

    def _refresh_hijack_row(self, agent: Agent) -> None:
        """Refresh the row after a transient hijack presentation changes."""
        from ._roster_generation import notify_roster_status_mutation

        notify_roster_status_mutation(self)
        refresh = getattr(self, "_refresh_agents_display", None)
        if callable(refresh):
            refresh(list_changed=False, defer_detail=True)


def _cheap_live_member(agent: Agent) -> bool:
    """Return whether a clan member is a live retarget candidate."""
    from ._hijack_decision import cheap_hijack_ingress_available

    return cheap_hijack_ingress_available(agent)


def _hijack_session_name(agent: Agent) -> str | None:
    """Return the session identity used for hijack target-level dedup."""
    try:
        session_candidate = getattr(agent, "agent_session", None)
        if isinstance(session_candidate, str) and session_candidate:
            return session_candidate
        if getattr(agent, "is_agent_session_root_entry", False):
            reference = agent.agent_session_reference_name()
            if isinstance(reference, str) and reference:
                return reference
    except Exception:
        return None
    return None


__all__ = [
    "AgentHijackActionMixin",
    "agent_can_offer_hijack",
    "agent_hijack_ingress_available",
]
