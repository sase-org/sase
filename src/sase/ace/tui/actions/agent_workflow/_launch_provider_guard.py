"""ACE hard-disabled-provider preflight for detached pending launches."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from sase.agent.launch_guard import (
    LaunchUnit,
    LaunchUnitInput,
    blocked_launch_units,
    plan_launch_units,
)
from sase.llm_provider import provider_disable_peek
from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_MODE_SOFT,
    TemporaryProviderDisable,
    disable_provider,
    disable_provider_until,
    enable_provider,
)
from sase.llm_provider.provider_priority_peek import peek_provider_routing_context

from ._pending_launch import (
    PendingLaunch,
    PendingLaunchStage,
    call_pending_launch_from_worker,
    cancel_pending_launch,
    pending_launch,
    pending_launch_can_show_modal,
    restore_pending_launch_prompt,
    set_pending_launch_stage,
)

if TYPE_CHECKING:
    from sase.ace.tui.modals.disabled_provider_launch_modal import (
        DisabledProviderLaunchDecision,
    )

log = logging.getLogger(__name__)

_GUARD_GROUP = "launch-provider-guard"


@dataclass
class _GuardUnitState:
    """One expanded unit the user is resolving, keyed by original index."""

    index: int
    prompt: str
    template_group: str | None
    swarm_xprompts: tuple[str, ...]
    aborted: bool = False
    remodeled: bool = False


@dataclass
class _ProviderGuardSession:
    """In-flight provider decisions for exactly one pending launch."""

    original_total: int
    units: list[_GuardUnitState] = field(default_factory=list)
    current_unit: LaunchUnit | None = None


class LaunchProviderGuardMixin:
    """Resolve hard-disabled providers after the prompt bar has unmounted."""

    def _continue_pending_launch(self, launch: PendingLaunch) -> None:
        """Implemented by :class:`LaunchSubmissionMixin`."""
        del launch
        raise NotImplementedError

    def _preflight_provider_disables(self, launch_id: str) -> None:
        """Plan hard-disable decisions from a pending-launch snapshot."""
        launch = pending_launch(self, launch_id)
        if launch is None:
            return
        set_pending_launch_stage(self, launch_id, PendingLaunchStage.PROVIDER_CHECK)
        snapshot = provider_disable_peek.peek_active_provider_disables()
        if not any(record.is_hard for record in snapshot.values()):
            self._continue_pending_launch(launch)
            return
        self._run_provider_guard_worker(
            lambda: self._plan_provider_guard_units(launch.prompt),
            lambda planned: self._on_provider_guard_planned(launch_id, planned),
            launch_id=launch_id,
        )

    def _plan_provider_guard_units(self, prompt: str) -> tuple[LaunchUnit, ...]:
        return plan_launch_units(prompt)

    def _on_provider_guard_planned(
        self, launch_id: str, planned: tuple[LaunchUnit, ...]
    ) -> None:
        launch = pending_launch(self, launch_id)
        if launch is None:
            return
        blocked = tuple(unit for unit in planned if unit.blocked)
        if not blocked:
            self._continue_pending_launch(launch)
            return
        launch.provider_guard_session = _ProviderGuardSession(
            original_total=planned[0].total if planned else 1,
            units=[
                _GuardUnitState(
                    index=unit.index,
                    prompt=unit.prompt,
                    template_group=unit.template_group,
                    swarm_xprompts=unit.swarm_xprompts,
                )
                for unit in planned
            ],
        )
        self._show_disabled_provider_panel(launch_id, blocked[0])

    def _show_disabled_provider_panel(self, launch_id: str, unit: LaunchUnit) -> None:
        launch = pending_launch(self, launch_id)
        session = self._provider_guard_session(launch)
        if launch is None or session is None:
            return
        if not pending_launch_can_show_modal(self):
            self._abort_provider_guard_launch(
                launch,
                "Launch needs a provider decision while another prompt or modal is active",
            )
            return

        from sase.ace.tui.modals.disabled_provider_launch_modal import (
            DisabledProviderLaunchModal,
        )
        from sase.ace.tui.modals.models_panel_duration import now as wall_now

        display = replace(unit, index=unit.index, total=session.original_total)
        session.current_unit = display
        set_pending_launch_stage(self, launch_id, PendingLaunchStage.PROVIDER_DECISION)
        self.push_screen(  # type: ignore[attr-defined]
            DisabledProviderLaunchModal(
                display,
                now=wall_now(),
                snapshot=provider_disable_peek.peek_active_provider_disables(),
                original_total=session.original_total,
            ),
            lambda decision: self._on_disabled_provider_decision(launch_id, decision),
        )

    def _on_disabled_provider_decision(
        self,
        launch_id: str,
        decision: DisabledProviderLaunchDecision | None,
    ) -> None:
        launch = pending_launch(self, launch_id)
        session = self._provider_guard_session(launch)
        if launch is None or session is None:
            return
        if decision is None or decision.action == "abort_unit":
            self._abort_current_blocked_unit(launch_id)
            return
        if decision.action == "abort_all":
            self._abort_provider_guard_launch(launch, "Launch aborted")
            return
        if decision.action == "pick_model":
            self._pick_model_for_current_unit(launch_id)
            return
        self._apply_provider_guard_write(launch_id, decision)

    def _abort_current_blocked_unit(self, launch_id: str) -> None:
        launch = pending_launch(self, launch_id)
        session = self._provider_guard_session(launch)
        if launch is None or session is None:
            return
        blocked = session.current_unit
        if blocked is not None:
            state = self._state_for_blocked_unit(session, blocked)
            if state is not None:
                state.aborted = True
        session.current_unit = None
        if not any(not unit.aborted for unit in session.units):
            self._abort_provider_guard_launch(launch, "Launch aborted")
            return
        self._recheck_provider_guard(launch_id)

    def _abort_provider_guard_launch(self, launch: PendingLaunch, reason: str) -> None:
        launch.provider_guard_session = None
        cancel_pending_launch(self, launch)
        restore_pending_launch_prompt(self, launch, reason=reason, explicit=False)

    def _pick_model_for_current_unit(self, launch_id: str) -> None:
        from sase.ace.tui.modals.custom_model_input_modal import CustomModelInputModal
        from sase.ace.tui.modals.model_picker_modal import (
            CUSTOM_SENTINEL,
            ModelPickerModal,
        )

        launch = pending_launch(self, launch_id)
        session = self._provider_guard_session(launch)
        unit = session.current_unit if session is not None else None
        if launch is None or session is None or unit is None:
            self._recheck_provider_guard(launch_id)
            return

        def on_picked(result: str | None) -> None:
            if pending_launch(self, launch_id) is None:
                return
            if result == CUSTOM_SENTINEL:
                self.push_screen(  # type: ignore[attr-defined]
                    CustomModelInputModal(title="Model for this agent"),
                    on_custom,
                )
                return
            if result is None:
                self._reshow_current_blocked_unit(launch_id)
                return
            self._apply_model_to_current_unit(launch_id, result)

        def on_custom(result: str | None) -> None:
            if pending_launch(self, launch_id) is None:
                return
            if result is None:
                self._reshow_current_blocked_unit(launch_id)
                return
            self._apply_model_to_current_unit(launch_id, result)

        self.push_screen(  # type: ignore[attr-defined]
            ModelPickerModal(
                title="Model for this agent",
                include_default_option=False,
                routing_context=peek_provider_routing_context(
                    provider_disables=provider_disable_peek.peek_active_provider_disables()
                ),
            ),
            on_picked,
        )

    def _apply_model_to_current_unit(self, launch_id: str, model: str) -> None:
        from sase.xprompt.directive_edit import set_prompt_model

        launch = pending_launch(self, launch_id)
        session = self._provider_guard_session(launch)
        unit = session.current_unit if session is not None else None
        if launch is None or session is None or unit is None:
            return
        state = self._state_for_blocked_unit(session, unit)
        if state is None:
            return
        state.prompt = set_prompt_model(state.prompt, model)
        state.remodeled = True
        self._recheck_provider_guard(launch_id)

    def _apply_provider_guard_write(
        self, launch_id: str, decision: DisabledProviderLaunchDecision
    ) -> None:
        launch = pending_launch(self, launch_id)
        session = self._provider_guard_session(launch)
        unit = session.current_unit if session is not None else None
        if launch is None or session is None or unit is None:
            self._recheck_provider_guard(launch_id)
            return
        providers = tuple(unit.blocking_providers)
        snapshot = provider_disable_peek.peek_active_provider_disables()

        def work() -> tuple[LaunchUnit, ...]:
            if decision.action == "enable":
                self._enable_providers(providers)
            elif decision.action == "soft_enable":
                self._soft_enable_providers(providers, snapshot)
            elif decision.action == "enable_provider" and decision.provider:
                self._enable_providers((decision.provider,))
            return self._blocked_from_session(session)

        self._run_provider_guard_worker(
            work,
            lambda blocked: self._on_provider_guard_rechecked(launch_id, blocked),
            launch_id=launch_id,
        )

    def _enable_providers(self, providers: tuple[str, ...]) -> None:
        for provider in providers:
            enable_provider(provider)

    def _soft_enable_providers(
        self,
        providers: tuple[str, ...],
        snapshot: dict[str, TemporaryProviderDisable],
    ) -> None:
        for provider in providers:
            record = snapshot.get(provider)
            if record is None:
                continue
            if record.expires_at is None:
                disable_provider(
                    provider,
                    None,
                    source="ace",
                    mode=PROVIDER_DISABLE_MODE_SOFT,
                )
            else:
                disable_provider_until(
                    provider,
                    record.expires_at,
                    source="ace",
                    mode=PROVIDER_DISABLE_MODE_SOFT,
                )

    def _on_provider_guard_rechecked(
        self, launch_id: str, blocked: tuple[LaunchUnit, ...]
    ) -> None:
        launch = pending_launch(self, launch_id)
        if launch is None:
            return
        if not blocked:
            self._finish_provider_guard_launch(launch)
            return
        self._show_disabled_provider_panel(launch_id, blocked[0])

    def _recheck_provider_guard(self, launch_id: str) -> None:
        launch = pending_launch(self, launch_id)
        session = self._provider_guard_session(launch)
        if launch is None or session is None:
            return
        self._run_provider_guard_worker(
            lambda: self._blocked_from_session(session),
            lambda blocked: self._on_provider_guard_rechecked(launch_id, blocked),
            launch_id=launch_id,
        )

    def _blocked_from_session(
        self, session: _ProviderGuardSession
    ) -> tuple[LaunchUnit, ...]:
        remaining = [unit for unit in session.units if not unit.aborted]
        if not remaining:
            return ()
        planned = blocked_launch_units(
            "",
            units=[
                LaunchUnitInput(
                    prompt=unit.prompt,
                    template_group=unit.template_group,
                    swarm_xprompts=unit.swarm_xprompts,
                )
                for unit in remaining
            ],
        )
        remapped: list[LaunchUnit] = []
        for unit in planned:
            if unit.index < 1 or unit.index > len(remaining):
                remapped.append(unit)
                continue
            original = remaining[unit.index - 1]
            remapped.append(
                replace(
                    unit,
                    index=original.index,
                    total=session.original_total,
                    prompt=original.prompt,
                    template_group=original.template_group,
                    swarm_xprompts=original.swarm_xprompts,
                )
            )
        return tuple(remapped)

    def _state_for_blocked_unit(
        self, session: _ProviderGuardSession, unit: LaunchUnit
    ) -> _GuardUnitState | None:
        for state in session.units:
            if state.index == unit.index:
                return state
        return None

    def _reshow_current_blocked_unit(self, launch_id: str) -> None:
        launch = pending_launch(self, launch_id)
        session = self._provider_guard_session(launch)
        unit = session.current_unit if session is not None else None
        if unit is None:
            self._recheck_provider_guard(launch_id)
            return
        self._show_disabled_provider_panel(launch_id, unit)

    def _finish_provider_guard_launch(self, launch: PendingLaunch) -> None:
        session = self._provider_guard_session(launch)
        launch.provider_guard_session = None
        if session is None:
            return
        surviving = [unit for unit in session.units if not unit.aborted]
        if not surviving:
            self._abort_provider_guard_launch(launch, "Launch aborted")
            return
        remodeled = any(unit.remodeled for unit in session.units)
        aborted = any(unit.aborted for unit in session.units)
        if not remodeled and not aborted:
            self._continue_pending_launch(launch)
            return
        if session.original_total == 1 and remodeled and not aborted:
            launch.prompt = surviving[0].prompt
            self._continue_pending_launch(launch)
            return
        launch.prompt = "\n---\n".join(unit.prompt for unit in surviving)
        payload = dict(launch.extra_payload or {})
        payload["launch_units"] = [
            {
                "prompt": unit.prompt,
                "template_group": unit.template_group,
                "swarm_xprompts": list(unit.swarm_xprompts),
            }
            for unit in surviving
        ]
        launch.extra_payload = payload
        self._continue_pending_launch(launch)

    def _run_provider_guard_worker(
        self, work: Any, on_success: Any, *, launch_id: str
    ) -> None:
        run_worker = getattr(self, "run_worker", None)

        def task() -> None:
            try:
                result = work()
            except Exception:
                log.warning(
                    "provider launch guard failed; launching without the panel",
                    exc_info=True,
                )
                call_pending_launch_from_worker(
                    self, self._on_provider_guard_failed_open, launch_id
                )
                return
            call_pending_launch_from_worker(self, on_success, result)

        if not callable(run_worker):
            task()
            return
        run_worker(
            task,
            thread=True,
            exclusive=False,
            group=f"{_GUARD_GROUP}:{launch_id}",
        )

    def _on_provider_guard_failed_open(self, launch_id: str) -> None:
        launch = pending_launch(self, launch_id)
        if launch is None:
            return
        launch.provider_guard_session = None
        self._continue_pending_launch(launch)

    def _provider_guard_session(
        self, launch: PendingLaunch | None
    ) -> _ProviderGuardSession | None:
        if launch is None:
            return None
        session = launch.provider_guard_session
        return session if isinstance(session, _ProviderGuardSession) else None


__all__ = ["LaunchProviderGuardMixin"]
