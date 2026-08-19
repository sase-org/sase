"""ACE preflight that resolves hard-disabled providers before a launch submits."""

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
from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_MODE_SOFT,
    TemporaryProviderDisable,
    disable_provider,
    disable_provider_until,
    enable_provider,
)
from sase.llm_provider import provider_disable_peek

from ._types import PromptContext

if TYPE_CHECKING:
    from sase.ace.tui.modals.disabled_provider_launch_modal import (
        DisabledProviderLaunchDecision,
    )

log = logging.getLogger(__name__)

_GUARD_GROUP = "launch-provider-guard"
_ABORT_TOAST = "Launch aborted; your prompt is still here."
_STALE_TOAST = "Launch cancelled; the prompt bar was closed while resolving providers."


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
    """In-flight ACE resolution of a blocked launch."""

    original_prompt: str
    keep_bar: bool
    original_total: int
    units: list[_GuardUnitState] = field(default_factory=list)
    current_unit: LaunchUnit | None = None


class LaunchProviderGuardMixin:
    """Run the hard-disable launch guard before ACE unmounts the prompt bar."""

    _prompt_context: PromptContext | None
    _provider_guard_session: _ProviderGuardSession | None = None

    def _submit_resolved_launch(
        self,
        prompt: str,
        *,
        keep_bar: bool = False,
        extra_payload: dict[str, object] | None = None,
    ) -> None:
        """Implemented by :class:`AgentLaunchStartMixin`."""
        raise NotImplementedError

    def _preflight_provider_disables(self, prompt: str, keep_bar: bool) -> None:
        """Refuse or resolve hard-disabled providers before unmounting the bar.

        The empty-disable path is synchronous and does not start a worker.
        Enumeration and provider writes run in ``launch-provider-guard``.
        """
        snapshot = provider_disable_peek.peek_active_provider_disables()
        if not any(record.is_hard for record in snapshot.values()):
            self._submit_resolved_launch(prompt, keep_bar=keep_bar)
            return
        self._run_provider_guard_worker(
            lambda: self._plan_provider_guard_units(prompt),
            lambda planned: self._on_provider_guard_planned(prompt, keep_bar, planned),
            prompt=prompt,
            keep_bar=keep_bar,
        )

    def _plan_provider_guard_units(self, prompt: str) -> tuple[LaunchUnit, ...]:
        return plan_launch_units(prompt)

    def _on_provider_guard_planned(
        self,
        prompt: str,
        keep_bar: bool,
        planned: tuple[LaunchUnit, ...],
    ) -> None:
        if not self._provider_guard_context_is_live():
            self._notify_stale_provider_guard()
            return
        blocked = tuple(unit for unit in planned if unit.blocked)
        if not blocked:
            self._submit_resolved_launch(prompt, keep_bar=keep_bar)
            return
        self._provider_guard_session = _ProviderGuardSession(
            original_prompt=prompt,
            keep_bar=keep_bar,
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
        self._show_disabled_provider_panel(blocked[0])

    def _show_disabled_provider_panel(self, unit: LaunchUnit) -> None:
        from sase.ace.tui.modals.disabled_provider_launch_modal import (
            DisabledProviderLaunchModal,
        )
        from sase.ace.tui.modals.models_panel_duration import now as wall_now

        session = self._provider_guard_session
        if session is None:
            return
        display = replace(unit, index=unit.index, total=session.original_total)
        session.current_unit = display
        self.push_screen(  # type: ignore[attr-defined]
            DisabledProviderLaunchModal(
                display,
                now=wall_now(),
                snapshot=provider_disable_peek.peek_active_provider_disables(),
                original_total=session.original_total,
            ),
            self._on_disabled_provider_decision,
        )

    def _on_disabled_provider_decision(
        self,
        decision: DisabledProviderLaunchDecision | None,
    ) -> None:
        session = self._provider_guard_session
        if session is None:
            return
        if not self._provider_guard_context_is_live():
            self._clear_provider_guard_session()
            self._notify_stale_provider_guard()
            return
        if decision is None or decision.action == "abort_unit":
            self._abort_current_blocked_unit()
            return
        if decision.action == "abort_all":
            self._abort_provider_guard_launch()
            return
        if decision.action == "pick_model":
            self._pick_model_for_current_unit()
            return
        self._apply_provider_guard_write(decision)

    def _abort_current_blocked_unit(self) -> None:
        session = self._provider_guard_session
        if session is None:
            return
        blocked = session.current_unit
        if blocked is not None:
            state = self._state_for_blocked_unit(blocked)
            if state is not None:
                state.aborted = True
        session.current_unit = None
        if not any(not unit.aborted for unit in session.units):
            self._abort_provider_guard_launch()
            return
        self._recheck_provider_guard()

    def _abort_provider_guard_launch(self) -> None:
        self._clear_provider_guard_session()
        self.notify(_ABORT_TOAST)  # type: ignore[attr-defined]

    def _pick_model_for_current_unit(self) -> None:
        from sase.ace.tui.modals.custom_model_input_modal import CustomModelInputModal
        from sase.ace.tui.modals.model_picker_modal import (
            CUSTOM_SENTINEL,
            ModelPickerModal,
        )

        session = self._provider_guard_session
        unit = session.current_unit if session is not None else None
        if unit is None:
            self._recheck_provider_guard()
            return

        def on_picked(result: str | None) -> None:
            if result == CUSTOM_SENTINEL:
                self.push_screen(  # type: ignore[attr-defined]
                    CustomModelInputModal(title="Model for this agent"),
                    on_custom,
                )
                return
            if result is None:
                self._reshow_current_blocked_unit()
                return
            self._apply_model_to_current_unit(result)

        def on_custom(result: str | None) -> None:
            if result is None:
                self._reshow_current_blocked_unit()
                return
            self._apply_model_to_current_unit(result)

        self.push_screen(  # type: ignore[attr-defined]
            ModelPickerModal(
                title="Model for this agent",
                include_default_option=False,
                provider_disables=provider_disable_peek.peek_active_provider_disables(),
            ),
            on_picked,
        )

    def _apply_model_to_current_unit(self, model: str) -> None:
        from sase.xprompt.directive_edit import set_prompt_model

        session = self._provider_guard_session
        unit = session.current_unit if session is not None else None
        if unit is None or session is None:
            return
        state = self._state_for_blocked_unit(unit)
        if state is None:
            return
        state.prompt = set_prompt_model(state.prompt, model)
        state.remodeled = True
        self._recheck_provider_guard()

    def _apply_provider_guard_write(
        self, decision: DisabledProviderLaunchDecision
    ) -> None:
        session = self._provider_guard_session
        unit = session.current_unit if session is not None else None
        if unit is None or session is None:
            self._recheck_provider_guard()
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
            return self._blocked_from_session()

        self._run_provider_guard_worker(
            work,
            self._on_provider_guard_rechecked,
            prompt=session.original_prompt,
            keep_bar=session.keep_bar,
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

    def _on_provider_guard_rechecked(self, blocked: tuple[LaunchUnit, ...]) -> None:
        if not self._provider_guard_context_is_live():
            self._clear_provider_guard_session()
            self._notify_stale_provider_guard()
            return
        if not blocked:
            self._finish_provider_guard_launch()
            return
        self._show_disabled_provider_panel(blocked[0])

    def _recheck_provider_guard(self) -> None:
        session = self._provider_guard_session
        if session is None:
            return

        def work() -> tuple[LaunchUnit, ...]:
            return self._blocked_from_session()

        self._run_provider_guard_worker(
            work,
            self._on_provider_guard_rechecked,
            prompt=session.original_prompt,
            keep_bar=session.keep_bar,
        )

    def _blocked_from_session(self) -> tuple[LaunchUnit, ...]:
        session = self._provider_guard_session
        if session is None:
            return ()
        remaining = [unit for unit in session.units if not unit.aborted]
        if not remaining:
            return ()
        planned = blocked_launch_units(
            session.original_prompt,
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

    def _state_for_blocked_unit(self, unit: LaunchUnit) -> _GuardUnitState | None:
        session = self._provider_guard_session
        if session is None:
            return None
        for state in session.units:
            if state.index == unit.index:
                return state
        return None

    def _reshow_current_blocked_unit(self) -> None:
        session = self._provider_guard_session
        unit = session.current_unit if session is not None else None
        if unit is None:
            self._recheck_provider_guard()
            return
        self._show_disabled_provider_panel(unit)

    def _finish_provider_guard_launch(self) -> None:
        session = self._provider_guard_session
        self._clear_provider_guard_session()
        if session is None:
            return
        if not self._provider_guard_context_is_live():
            self._notify_stale_provider_guard()
            return
        surviving = [unit for unit in session.units if not unit.aborted]
        if not surviving:
            self.notify(_ABORT_TOAST)  # type: ignore[attr-defined]
            return
        remodeled = any(unit.remodeled for unit in session.units)
        aborted = any(unit.aborted for unit in session.units)
        if not remodeled and not aborted:
            self._submit_resolved_launch(
                session.original_prompt, keep_bar=session.keep_bar
            )
            return
        if session.original_total == 1 and remodeled and not aborted:
            self._submit_resolved_launch(surviving[0].prompt, keep_bar=session.keep_bar)
            return
        joined = "\n---\n".join(unit.prompt for unit in surviving)
        payload = [
            {
                "prompt": unit.prompt,
                "template_group": unit.template_group,
                "swarm_xprompts": list(unit.swarm_xprompts),
            }
            for unit in surviving
        ]
        self._submit_resolved_launch(
            joined,
            keep_bar=session.keep_bar,
            extra_payload={"launch_units": payload},
        )

    def _run_provider_guard_worker(
        self,
        work: Any,
        on_success: Any,
        *,
        prompt: str,
        keep_bar: bool,
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
                self._call_from_ui(
                    self._on_provider_guard_failed_open, prompt, keep_bar
                )
                return
            self._call_from_ui(on_success, result)

        if not callable(run_worker):
            task()
            return
        run_worker(
            task,
            thread=True,
            exclusive=True,
            group=_GUARD_GROUP,
        )

    def _on_provider_guard_failed_open(self, prompt: str, keep_bar: bool) -> None:
        self._clear_provider_guard_session()
        if not self._provider_guard_context_is_live():
            self._notify_stale_provider_guard()
            return
        self._submit_resolved_launch(prompt, keep_bar=keep_bar)

    def _call_from_ui(self, callback: Any, *args: Any) -> None:
        caller = getattr(self, "call_from_thread", None)
        if callable(caller):
            caller(callback, *args)
            return
        callback(*args)

    def _provider_guard_context_is_live(self) -> bool:
        if self._prompt_context is None:
            return False
        mounted = getattr(self, "_mounted_prompt_bar", None)
        if callable(mounted):
            return mounted() is not None
        return True

    def _notify_stale_provider_guard(self) -> None:
        self.notify(_STALE_TOAST, severity="warning")  # type: ignore[attr-defined]

    def _clear_provider_guard_session(self) -> None:
        self._provider_guard_session = None
