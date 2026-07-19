"""Uninstall planning and execution for SASE plugins."""

from __future__ import annotations

import time
from dataclasses import dataclass

from sase.plugins.catalog import PluginCatalogEntry, find_plugin, load_plugin_catalog
from sase.plugins.catalog import suggest_plugins
from sase.uv_tool.commands import build_uninstall
from sase.uv_tool.detect import NotUvToolInstall, probe_uv_tool_install
from sase.uv_tool.errors import NotAUvToolInstallError
from sase.uv_tool.overrides import write_editable_overrides
from sase.uv_tool.preflight import missing_local_requirements_error
from sase.uv_tool.receipt import Requirement, load_receipt
from sase.uv_tool.runner import UvChangeSet, run_uv

from ._operations_common import (
    ClockFn,
    LoadFn,
    NotUvTool,
    ProbeFn,
    RunUvFn,
    load_catalog,
    match_injected,
    short_display_name,
)


@dataclass(frozen=True)
class AlreadyAbsent:
    """The plugin is known but not injected — uninstall is a no-op success.

    Removing something that is already gone is idempotent, so this is reported as
    a success (the ChangeSpecI exits 0 and the TUI toasts neutrally), unlike update's
    :class:`NotInstalled`, which is an error.
    """

    name: str


@dataclass(frozen=True)
class UninstallUnknown:
    """The ``<plugin>`` name matched neither the receipt nor the catalog."""

    query: str
    suggestions: tuple[PluginCatalogEntry, ...]


@dataclass(frozen=True)
class UninstallReady:
    """Resolved and ready to uninstall: *argv* is the exact ``uv`` command.

    *requirement* is the matched injected plugin (the receipt is the source of
    truth); *display_name* is the short, friendly name for output.
    """

    requirement: Requirement
    display_name: str
    argv: list[str]

    @property
    def dist_name(self) -> str:
        """The distribution name being removed (e.g. ``sase-github``)."""
        return self.requirement.name

    @property
    def normalized_name(self) -> str:
        """PEP 503-normalized distribution name of the removed plugin."""
        return self.requirement.normalized_name


#: A planned uninstall: one of these four typed outcomes.
UninstallPlan = NotUvTool | AlreadyAbsent | UninstallUnknown | UninstallReady


@dataclass(frozen=True)
class UninstallOutcome:
    """The result of executing an :class:`UninstallReady` plan."""

    plan: UninstallReady
    change_set: UvChangeSet
    elapsed: float


def plan_uninstall(
    query: str,
    *,
    refresh: bool = False,
    offline: bool = False,
    load_fn: LoadFn = load_plugin_catalog,
    probe_fn: ProbeFn = probe_uv_tool_install,
) -> UninstallPlan:
    """Plan ``sase plugin uninstall <query>`` without running ``uv``.

    Probes the install, then reads the receipt as the source of truth for the
    injected set and tries to match *query* against it (the same short/repo/
    full-name normalization as update), so an installed plugin — even a community
    one absent from the catalog — resolves with no catalog fetch. A receipt match
    returns an :class:`UninstallReady` carrying the exact ``uv`` argv. Only on a
    receipt *miss* is the catalog consulted, to tell a known-but-already-absent
    plugin (:class:`AlreadyAbsent`, a no-op success) apart from an unknown name
    (:class:`UninstallUnknown`, with suggestions). Raises
    :class:`~sase.plugins.catalog.PluginCatalogError` /
    :class:`~sase.uv_tool.errors.ReceiptError` for those failure modes, exactly
    as install/update do.
    """
    install = probe_fn()
    if isinstance(install, NotUvToolInstall):
        return NotUvTool(NotAUvToolInstallError(install))

    receipt = load_receipt(install.receipt_path)
    injected = match_injected(receipt, query)
    if injected is not None:
        recon = receipt.reconstruct(remove=injected.normalized_name)
        if (error := missing_local_requirements_error(recon)) is not None:
            return NotUvTool(error)
        overrides_path = write_editable_overrides((recon.primary, *recon.plugins))
        argv = build_uninstall(
            receipt,
            remove=injected.normalized_name,
            color="never",
            overrides=str(overrides_path) if overrides_path is not None else None,
        )
        return UninstallReady(
            requirement=injected,
            display_name=short_display_name(injected.name),
            argv=argv,
        )

    catalog = load_catalog(load_fn, refresh=refresh, offline=offline)
    entry = find_plugin(catalog, query)
    if entry is not None:
        return AlreadyAbsent(entry.name)
    return UninstallUnknown(query, suggest_plugins(catalog, query))


def execute_uninstall(
    plan: UninstallReady,
    *,
    run_fn: RunUvFn = run_uv,
    clock: ClockFn = time.monotonic,
) -> UninstallOutcome:
    """Run the ``uv`` re-install (minus the target) for a ready plan.

    Raises :class:`~sase.uv_tool.errors.UvToolError` if ``uv`` fails; the caller
    catches it.
    """
    start = clock()
    change_set = run_fn(plan.argv)
    elapsed = max(0.0, clock() - start)
    return UninstallOutcome(plan=plan, change_set=change_set, elapsed=elapsed)
