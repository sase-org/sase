"""SASE self-update actions for the Config Center Updates tab."""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import time
from typing import TYPE_CHECKING, Any, Literal

from sase.ace.tui.actions.task_actions import (
    TrackedTaskCompletion,
    TrackedTaskResult,
)
from sase.plugins.render_common import humanize_duration
from sase.uv_tool.commands import build_upgrade_all
from sase.uv_tool.detect import NotUvToolInstall, UvToolInstall
from sase.uv_tool.errors import NotAUvToolInstallError, ReceiptError, UvToolError
from sase.uv_tool.receipt import ToolReceipt, load_receipt
from sase.uv_tool.render import UpdateSummary, summarize_update
from sase.uv_tool.runner import run_uv
from sase.version._utils import normalize_distribution_name

from .plugin_action_confirm_modal import (
    PluginActionConfirmModal,
    PluginActionConfirmResult,
    PluginActionVariant,
)

_CORE_DIST_KEYS = {
    normalize_distribution_name("sase"),
    normalize_distribution_name("sase-core-rs"),
}


def installed_version(name: str) -> str | None:
    """Return the installed version of distribution *name*, or ``None``."""
    try:
        return importlib_metadata.version(name)
    except importlib_metadata.PackageNotFoundError:
        return None
    except Exception:  # noqa: BLE001 - version display must never fail the task.
        return None


def load_receipt_for_summary(install: object | None) -> ToolReceipt | None:
    """Load the uv-tool receipt when available, tolerating parse failures."""
    if not isinstance(install, UvToolInstall):
        return None
    try:
        return load_receipt(install.receipt_path)
    except ReceiptError:
        return None


def run_sase_update_summary(install: object | None) -> tuple[UpdateSummary, float]:
    """Run ``uv tool upgrade sase`` and summarize the changed package set."""
    argv = build_upgrade_all(color="never")
    start = time.monotonic()
    change_set = run_uv(argv)
    elapsed = max(0.0, time.monotonic() - start)
    return (
        summarize_update(
            change_set,
            load_receipt_for_summary(install),
            current_version=installed_version,
        ),
        elapsed,
    )


def sase_update_success_message(summary: UpdateSummary, elapsed: float) -> str:
    """Concise toast for a successful ``sase update`` run."""
    if not summary.changed:
        return "Already up to date."

    core_updated = any(
        outcome.is_update
        and normalize_distribution_name(outcome.name) in _CORE_DIST_KEYS
        for outcome in summary.outcomes
    )
    plugin_count = len(summary.updated_plugins)
    dependency_count = sum(
        1
        for outcome in summary.updated_dependencies
        if normalize_distribution_name(outcome.name) not in _CORE_DIST_KEYS
    )

    subjects: list[str] = []
    if core_updated:
        subjects.append("sase")
    if plugin_count:
        subjects.append(f"{plugin_count} {_plural(plugin_count, 'plugin')}")
    if not subjects and dependency_count:
        subjects.append(f"{dependency_count} {_plural(dependency_count, 'dependency')}")
    if not subjects:
        subjects.append("packages")

    return f"Updated {' + '.join(subjects)} in {humanize_duration(elapsed)}"


def _plural(count: int, singular: str) -> str:
    if count == 1:
        return singular
    if singular.endswith("y"):
        return f"{singular[:-1]}ies"
    return f"{singular}s"


class SaseUpdateActionsMixin:
    """Run ``sase update`` from the Updates tab."""

    if TYPE_CHECKING:
        _loading: bool
        _sase_update_restart_hint: bool
        _uv_tool: object | None
        app: Any
        is_mounted: bool

        def _notify(
            self,
            message: str,
            *,
            severity: Literal["information", "warning", "error"] = "information",
        ) -> None: ...

        def _run_sase_update_summary(
            self, install: object | None
        ) -> tuple[UpdateSummary, float]: ...

        def _start_load(self, *, force: bool) -> None: ...

    def action_update_sase(self) -> None:
        """Preview and run ``sase update`` as a tracked background task."""
        if self._loading:
            return
        if isinstance(self._uv_tool, NotUvToolInstall):
            self._notify(str(NotAUvToolInstallError(self._uv_tool)), severity="warning")
            return

        modal = PluginActionConfirmModal(
            title="Update SASE",
            intro="Confirm to upgrade sase core and every installed plugin.",
            variants=[
                PluginActionVariant(
                    key="update-sase",
                    label="sase update",
                    argv=tuple(build_upgrade_all()),
                    summary="Upgrades sase core + every installed plugin",
                )
            ],
            panel_title="Confirm SASE update",
            icon="↑",
        )

        def _on_confirmed(result: PluginActionConfirmResult | None) -> None:
            if result is None:
                return
            self._submit_sase_update_task()

        self.app.push_screen(modal, _on_confirmed)

    def _submit_sase_update_task(self) -> None:
        """Run the self-update engine in the shared tracked-task system."""
        install = self._uv_tool

        def task() -> TrackedTaskResult[UpdateSummary]:
            try:
                summary, elapsed = self._run_sase_update_summary(install)
            except UvToolError as exc:
                return TrackedTaskResult(
                    success=False,
                    message=str(exc),
                    error=str(exc),
                )
            return TrackedTaskResult(
                success=True,
                message=sase_update_success_message(summary, elapsed),
                payload=summary,
            )

        submit = getattr(self.app, "_submit_tracked_task", None)
        if submit is None:
            return
        submit(
            "sase-update",
            "sase",
            "",
            task,
            display_name="sase update",
            dedup_key="sase-update",
            duplicate_message="A sase update is already running.",
            on_complete=self._on_sase_update_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )

    def _on_sase_update_complete(
        self, completion: TrackedTaskCompletion[UpdateSummary]
    ) -> None:
        """Toast the outcome and refresh installed/latest versions in place."""
        if completion.success:
            self._notify(completion.message)
            self._sase_update_restart_hint = bool(
                completion.payload is not None and completion.payload.changed
            )
            if self.is_mounted and not self._loading:
                self._start_load(force=False)
        else:
            detail = completion.error or completion.message
            self._notify(f"sase update failed: {detail}", severity="error")


_installed_version = installed_version
_load_receipt_for_summary = load_receipt_for_summary
_run_sase_update_summary = run_sase_update_summary
_sase_update_success_message = sase_update_success_message
