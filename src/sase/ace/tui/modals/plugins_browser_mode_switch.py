"""Install-mode switching actions for the Config Center Updates tab."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

from sase.ace.tui.actions.proc_actions import (
    TrackedProcCompletion,
    TrackedProcResult,
)
from sase.ace.update_receipt import build_update_receipt, write_pending_update_toast
from sase.config import load_merged_config
from sase.mode_switch import execute_mode_switch, plan_mode_switch
from sase.mode_switch.models import ModeSwitchResult, SwitchPlan, TargetMode
from sase.mode_switch.render import render_mode_switch_plan
from sase.uv_tool.detect import NotUvToolInstall
from sase.uv_tool.errors import NotAUvToolInstallError, UvToolError
from sase.version.inventory import collect_runtime_version_inventory

from .plugin_action_confirm_modal import (
    PluginActionConfirmModal,
    PluginActionConfirmResult,
    PluginActionVariant,
)


@dataclass(frozen=True)
class ModeSwitchPreview:
    """Off-thread mode-switch planning result."""

    plans: tuple[SwitchPlan, ...] = ()
    error: str | None = None


def make_mode_switch_preview(
    install: object | None,
    *,
    current_mode: str | None,
) -> ModeSwitchPreview:
    """Plan the next install-mode switch direction for the TUI."""
    if not install or isinstance(install, NotUvToolInstall):
        return ModeSwitchPreview(error="sase is not a `uv tool` install")
    targets: tuple[TargetMode, ...]
    if current_mode == "dev":
        targets = ("pypi",)
    elif current_mode == "mixed":
        targets = ("dev", "pypi")
    else:
        targets = ("dev",)
    try:
        plans = tuple(
            plan_mode_switch(
                install,  # type: ignore[arg-type]
                target_mode=target,
                config=load_merged_config(),
                inventory_fn=collect_runtime_version_inventory,
            )
            for target in targets
        )
    except UvToolError as exc:
        return ModeSwitchPreview(error=str(exc))
    return ModeSwitchPreview(plans=plans)


def _mode_switch_success_message(result: ModeSwitchResult, elapsed: float) -> str:
    return f"Switched to {result.plan.target_label} in {elapsed:.1f}s"


class ModeSwitchActionsMixin:
    """Switch between PyPI and editable install modes from the Updates tab."""

    if TYPE_CHECKING:
        _loading: bool
        _mode_switch_plan_worker: Any | None
        _uv_tool: object | None
        _install_mode: str | None
        app: Any

        def _notify(
            self,
            message: str,
            *,
            severity: Literal["information", "warning", "error"] = "information",
        ) -> None: ...

        def _close_admin_center_after_sase_update(self) -> None: ...

        def _restart_after_update(self, message: str) -> None: ...

        def _start_load(self, *, force: bool) -> None: ...

    def action_switch_mode(self) -> None:
        """Open a confirmable install-mode switch preview."""
        if self._loading or self._mode_switch_plan_worker is not None:
            return
        if isinstance(self._uv_tool, NotUvToolInstall):
            self._notify(str(NotAUvToolInstallError(self._uv_tool)), severity="warning")
            return

        install = self._uv_tool
        current_mode = self._install_mode

        def task() -> ModeSwitchPreview:
            return make_mode_switch_preview(install, current_mode=current_mode)

        self._mode_switch_plan_worker = self.run_worker(  # type: ignore[attr-defined]
            task, thread=True, exclusive=True, group="mode-switch-plan"
        )

    def _on_mode_switch_preview(self, preview: ModeSwitchPreview | None) -> None:
        if preview is None:
            return
        if preview.error is not None:
            self._notify(preview.error, severity="error")
            return
        plans = tuple(plan for plan in preview.plans if plan.changed)
        if not plans:
            self._notify("Install mode is already current.")
            return
        self._open_mode_switch_modal(plans)

    def _open_mode_switch_modal(self, plans: tuple[SwitchPlan, ...]) -> None:
        variants = [
            PluginActionVariant(
                key=plan.target_mode,
                label=plan.target_label,
                argv=("sase", "update", "--to", plan.target_mode),
                summary=f"{plan.current_label} -> {plan.target_label}",
                details=_mode_switch_details(plan),
            )
            for plan in plans
        ]
        modal = PluginActionConfirmModal(
            title="Switch install mode",
            intro="Confirm to rewrite the uv-tool receipt for the selected mode.",
            variants=variants,
            panel_title="Confirm mode switch",
            icon="⇄",
        )
        by_key = {plan.target_mode: plan for plan in plans}

        def _on_confirmed(result: PluginActionConfirmResult | None) -> None:
            if result is None:
                return
            if result.variant_key not in {"dev", "pypi"}:
                return
            plan = by_key.get(cast(TargetMode, result.variant_key))
            if plan is None:
                return
            self._submit_mode_switch_task(plan)
            self._close_admin_center_after_sase_update()

        self.app.push_screen(modal, _on_confirmed)

    def _submit_mode_switch_task(self, plan: SwitchPlan) -> None:
        def task() -> TrackedProcResult[ModeSwitchResult]:
            start = time.monotonic()
            try:
                result = execute_mode_switch(plan)
            except UvToolError as exc:
                return TrackedProcResult(
                    success=False,
                    message=str(exc),
                    error=str(exc),
                )
            elapsed = max(0.0, time.monotonic() - start)
            message = _mode_switch_success_message(result, elapsed)
            return TrackedProcResult(success=True, message=message, payload=result)

        submit = getattr(self.app, "_submit_session_worker", None)
        if submit is None:
            return
        submit(
            "mode-switch",
            task,
            display_name=f"switch to {plan.target_mode}",
            cl_name=plan.target_mode,
            on_complete=self._on_mode_switch_complete,
        )

    def _on_mode_switch_complete(
        self, completion: TrackedProcCompletion[ModeSwitchResult]
    ) -> None:
        if completion.success and completion.payload is not None:
            receipt = build_update_receipt(completion.payload)
            if receipt is not None:
                write_pending_update_toast(receipt)
            self._restart_after_update(completion.message)
            return
        detail = completion.error or completion.message
        self._notify(f"mode switch failed: {detail}", severity="error")


def _mode_switch_details(plan: SwitchPlan) -> tuple[str, ...]:
    details: list[str] = []
    for package in plan.packages[:6]:
        details.append(
            f"{package.name}: {package.current_version or '-'} -> "
            f"{package.target_version or '-'} ({package.source})"
        )
    overflow = len(plan.packages) - len(details)
    if overflow > 0:
        details.append(f"...and {overflow} more package(s)")
    for command in plan.commands[:4]:
        details.append("run: " + " ".join(command.command))
    return tuple(details)


_ModeSwitchPreview = ModeSwitchPreview
_make_mode_switch_preview = make_mode_switch_preview
