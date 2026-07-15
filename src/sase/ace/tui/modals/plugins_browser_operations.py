"""Operation wrapper methods for the Config Center Updates plugin browser."""

from __future__ import annotations

from collections.abc import Collection
from inspect import Parameter, signature
from typing import Any

from sase.plugins.operations import (
    InstallManyOutcome,
    InstallManyReady,
    InstallOutcome,
    InstallReady,
    UninstallOutcome,
    UninstallReady,
    UpdateOutcome,
    UpdateReady,
)
from sase.uv_tool.receipt import ToolReceipt
from sase.uv_tool.render import UpdateSummary

from .plugins_browser_dev_update import DevUpdatePreview
from .plugins_browser_install import InstallManyPreview, InstallPreview
from .plugins_browser_uninstall import UninstallPreview
from .plugins_browser_update import UpdatePreview


class PluginsBrowserOperationsMixin:
    """Thin indirection layer over plugin/core update operations.

    The pane module has historically exposed underscored callables that tests
    monkeypatch directly. These methods intentionally resolve through that
    module at call time, preserving those patch points after the file split.
    """

    def _make_install_preview(self, name: str, *, offline: bool) -> InstallPreview:
        from . import plugins_browser_pane as pane_module

        return pane_module._plan_install_preview(name, offline=offline)

    def _make_install_many_preview(
        self, names: tuple[str, ...], *, offline: bool
    ) -> InstallManyPreview:
        from . import plugins_browser_pane as pane_module

        return pane_module._plan_install_many_preview(names, offline=offline)

    @staticmethod
    def _execute_install(plan: InstallReady, *, run_fn: Any = None) -> InstallOutcome:
        from . import plugins_browser_pane as pane_module

        if run_fn is None:
            return pane_module.execute_install(plan)
        return pane_module.execute_install(plan, run_fn=run_fn)

    @staticmethod
    def _execute_install_many(
        plan: InstallManyReady, *, run_fn: Any = None
    ) -> InstallManyOutcome:
        from . import plugins_browser_pane as pane_module

        if run_fn is None:
            return pane_module.execute_install_many(plan)
        return pane_module.execute_install_many(plan, run_fn=run_fn)

    def _make_update_preview(
        self, query: str | None, *, all_plugins: bool, offline: bool
    ) -> UpdatePreview:
        from . import plugins_browser_pane as pane_module

        return pane_module._plan_update_preview(
            query, all_plugins=all_plugins, offline=offline
        )

    @staticmethod
    def _execute_update(plan: UpdateReady, *, run_fn: Any = None) -> UpdateOutcome:
        from . import plugins_browser_pane as pane_module

        if run_fn is None:
            return pane_module.execute_update(plan)
        return pane_module.execute_update(plan, run_fn=run_fn)

    @staticmethod
    def _make_plugin_dev_update_preview(
        query: str | None,
        *,
        all_plugins: bool,
        receipt: object | None,
    ) -> DevUpdatePreview:
        from . import plugins_browser_pane as pane_module

        return pane_module._make_plugin_dev_update_preview(
            query,
            all_plugins=all_plugins,
            receipt=receipt if isinstance(receipt, ToolReceipt) else None,
        )

    @staticmethod
    def _execute_dev_update(plan: Any, *, run: Any = None) -> Any:
        from . import plugins_browser_pane as pane_module

        execute = pane_module._execute_tui_dev_update
        if run is None or not callable_accepts_keyword(execute, "run"):
            return execute(plan)
        return execute(plan, run=run)

    def _make_uninstall_preview(self, query: str, *, offline: bool) -> UninstallPreview:
        from . import plugins_browser_pane as pane_module

        return pane_module._plan_uninstall_preview(query, offline=offline)

    @staticmethod
    def _execute_uninstall(
        plan: UninstallReady, *, run_fn: Any = None
    ) -> UninstallOutcome:
        from . import plugins_browser_pane as pane_module

        if run_fn is None:
            return pane_module.execute_uninstall(plan)
        return pane_module.execute_uninstall(plan, run_fn=run_fn)

    @staticmethod
    def _run_sase_update_summary(
        install: object | None, *, run_fn: Any = None
    ) -> tuple[UpdateSummary, float]:
        from . import plugins_browser_pane as pane_module

        summarize = pane_module.run_sase_update_summary
        if run_fn is None:
            return summarize(install)
        if callable_accepts_keyword(summarize, "run_fn"):
            return summarize(install, run_fn=run_fn)
        return summarize(install)

    @staticmethod
    def _run_planned_sase_update_summary(
        argv: tuple[str, ...],
        packages: tuple[Any, ...],
        *,
        run_fn: Any = None,
    ) -> tuple[UpdateSummary, float]:
        from . import plugins_browser_pane as pane_module

        summarize = pane_module.run_planned_sase_update_summary
        if run_fn is None:
            return summarize(argv, packages)
        if callable_accepts_keyword(summarize, "run_fn"):
            return summarize(argv, packages, run_fn=run_fn)
        return summarize(argv, packages)

    @staticmethod
    def _make_sase_update_preview(
        receipt: object | None,
        *,
        already_refreshed_roots: Collection[str] = (),
    ) -> DevUpdatePreview:
        from . import plugins_browser_pane as pane_module

        make_preview = pane_module._make_sase_dev_update_preview
        typed_receipt = receipt if isinstance(receipt, ToolReceipt) else None
        if callable_accepts_keyword(make_preview, "already_refreshed_roots"):
            return make_preview(
                typed_receipt,
                already_refreshed_roots=already_refreshed_roots,
            )
        return make_preview(typed_receipt)

    @staticmethod
    def _worker_error_text(worker: Any, *, kind: str = "install") -> str:
        if worker.error:
            return str(worker.error)
        return f"Could not plan the {kind}."


def callable_accepts_keyword(fn: Any, name: str) -> bool:
    try:
        params = signature(fn).parameters.values()
    except (TypeError, ValueError):
        return False
    for param in params:
        if param.kind is Parameter.VAR_KEYWORD:
            return True
        if param.name == name and param.kind in (
            Parameter.KEYWORD_ONLY,
            Parameter.POSITIONAL_OR_KEYWORD,
        ):
            return True
    return False
