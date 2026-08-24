"""Provider-drain prompt and submission for `ProviderRoutingModal`."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from sase.ace.tui.actions.agent_durable import submit_provider_drain

from .model_picker_modal import ModelPickerModal
from .models_panel_provider_state import ProviderRoutingSnapshot, ProviderWriteOutcome
from .provider_drain_prompt_modal import (
    ProviderDrainPromptDecision,
    ProviderDrainPromptModal,
)

if TYPE_CHECKING:
    from textual.screen import ModalScreen as _MixinBase
else:
    _MixinBase = object


def _completion_count_text(count: int, singular: str) -> str:
    suffix = "" if count == 1 else "s"
    return f"{count} {singular}{suffix}"


def _drain_completion_message(payload: Mapping[str, Any] | None) -> str:
    """Return a compact toast from the stable drain result envelope."""
    counts = payload.get("counts") if isinstance(payload, Mapping) else None
    if not isinstance(counts, Mapping):
        return "Provider drain completed."
    relaunched = _payload_count(counts, "relaunched")
    skipped = _payload_count(counts, "skipped")
    failed = _payload_count(counts, "failed")
    message = (
        f"Relaunched {_completion_count_text(relaunched, 'agent')}; "
        f"{skipped} left alone"
    )
    if failed:
        message = f"{message}; {failed} failed"
    return message


def _payload_count(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, int) and value >= 0:
        return value
    return 0


class ProviderRoutingDrainMixin(_MixinBase):
    """Offer and submit a provider drain after a hard-disable write."""

    if TYPE_CHECKING:
        _snapshot: ProviderRoutingSnapshot

        def _now(self) -> float: ...

    def _maybe_prompt_provider_drain(self, outcome: ProviderWriteOutcome) -> None:
        if outcome.drain_preview_error:
            self.notify(  # type: ignore[attr-defined]
                f"Provider drain preview unavailable: {outcome.drain_preview_error}",
                severity="warning",
            )
            return
        plan = outcome.drain_preview
        if plan is None:
            return
        self.app.push_screen(  # type: ignore[attr-defined]
            ProviderDrainPromptModal(plan, now=self._now()),
            callback=lambda decision: self._on_provider_drain_decision(plan, decision),
        )

    def _on_provider_drain_decision(
        self,
        plan: Any,
        decision: ProviderDrainPromptDecision | None,
    ) -> None:
        if decision is None or decision.action == "leave":
            return
        if decision.action == "pick_model":
            self.app.push_screen(  # type: ignore[attr-defined]
                ModelPickerModal(
                    title=f"Relaunch {plan.provider.upper()} Agents On",
                    include_default_option=False,
                    provider_disables=self._snapshot.provider_disables,
                ),
                callback=lambda model: self._on_provider_drain_model(plan, model),
            )
            return
        self._submit_provider_drain(plan.provider)

    def _on_provider_drain_model(self, plan: Any, model: str | None) -> None:
        if model is None:
            return
        self._submit_provider_drain(plan.provider, model=model)

    def _submit_provider_drain(
        self, provider: str, *, model: str | None = None
    ) -> None:
        app = self.app  # type: ignore[attr-defined]

        def on_complete(completion: Any) -> None:
            if completion.collision:
                app.notify(
                    f"A provider drain is already running for {provider.upper()}.",
                    severity="warning",
                )
                return
            if not completion.success:
                app.notify(
                    (
                        "Provider drain proc "
                        f"{completion.proc_info.proc_id} failed; inspect Procs: "
                        f"{completion.message}"
                    ),
                    severity="error",
                )
                return
            app.notify(_drain_completion_message(completion.payload))

        try:
            submitted = submit_provider_drain(
                app,
                provider=provider,
                model=model,
                on_complete=on_complete,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced in TUI toast.
            self.notify(f"Could not submit provider drain: {exc}", severity="error")  # type: ignore[attr-defined]
            return
        if submitted:
            suffix = f" on {model}" if model else ""
            self.notify(f"Drain submitted for {provider.upper()}{suffix}; watch Procs.")  # type: ignore[attr-defined]
