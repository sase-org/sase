"""Update planning and execution for SASE plugins."""

from __future__ import annotations

import time
from dataclasses import dataclass

from sase.plugins.catalog import PluginCatalogEntry, find_plugin, load_plugin_catalog
from sase.plugins.catalog import suggest_plugins
from sase.uv_tool.commands import build_upgrade_packages
from sase.uv_tool.detect import NotUvToolInstall, probe_uv_tool_install
from sase.uv_tool.errors import NotAUvToolInstallError
from sase.uv_tool.overrides import write_editable_overrides
from sase.uv_tool.preflight import missing_local_requirements_error
from sase.uv_tool.receipt import Requirement, ToolReceipt, load_receipt
from sase.uv_tool.runner import UvChangeSet, run_uv

from ._operations_common import (
    ClockFn,
    LoadFn,
    NotUvTool,
    ProbeFn,
    RunUvFn,
    load_catalog,
    match_injected,
)


@dataclass(frozen=True)
class NoPlugins:
    """``update --all`` was requested but no plugins are injected."""


@dataclass(frozen=True)
class NotInstalled:
    """The named plugin exists in the catalog but is not injected into sase."""

    name: str


@dataclass(frozen=True)
class UpdateUnknown:
    """The ``<plugin>`` name matched neither the receipt nor the catalog."""

    query: str
    suggestions: tuple[PluginCatalogEntry, ...]


@dataclass(frozen=True)
class UpdateReady:
    """Resolved and ready to update: *argv* is the exact ``uv`` command.

    *targets* are the distribution names that will be ``--upgrade-package``-ed;
    *all_plugins* records whether this was an ``--all`` request (for messaging).
    """

    argv: list[str]
    targets: tuple[str, ...]
    all_plugins: bool


#: A planned update: one of these five typed outcomes.
UpdatePlan = NotUvTool | NoPlugins | NotInstalled | UpdateUnknown | UpdateReady


@dataclass(frozen=True)
class UpdateOutcome:
    """The result of executing an :class:`UpdateReady` plan."""

    plan: UpdateReady
    change_set: UvChangeSet
    elapsed: float


def plan_update(
    query: str | None,
    *,
    all_plugins: bool = False,
    refresh: bool = False,
    offline: bool = False,
    load_fn: LoadFn = load_plugin_catalog,
    probe_fn: ProbeFn = probe_uv_tool_install,
) -> UpdatePlan:
    """Plan ``sase plugin update`` (single or ``--all``) without running ``uv``.

    Probes the install, reads the receipt as the source of truth for the
    injected set, and resolves the target(s). Returns a terminal outcome
    (:class:`NotUvTool`, :class:`NoPlugins`, :class:`NotInstalled`,
    :class:`UpdateUnknown`) or an :class:`UpdateReady` carrying the exact ``uv``
    argv. Raises :class:`~sase.plugins.catalog.PluginCatalogError` /
    :class:`~sase.uv_tool.errors.ReceiptError` for those failure modes, exactly
    as the ChangeSpecI did before.

    Caller contract: when *all_plugins* is false, *query* must be non-empty
    (CLI usage validation lives in the handler, not here).
    """
    install = probe_fn()
    if isinstance(install, NotUvToolInstall):
        return NotUvTool(NotAUvToolInstallError(install))

    receipt = load_receipt(install.receipt_path)

    if all_plugins:
        targets = tuple(plugin.name for plugin in receipt.deduped_injected_plugins())
        if not targets:
            return NoPlugins()
    else:
        resolved = _resolve_update_target(
            receipt, str(query), load_fn=load_fn, refresh=refresh, offline=offline
        )
        if isinstance(resolved, (NotInstalled, UpdateUnknown)):
            return resolved
        targets = (resolved.name,)

    recon = receipt.reconstruct()
    if (error := missing_local_requirements_error(recon)) is not None:
        return NotUvTool(error)
    overrides_path = write_editable_overrides((recon.primary, *recon.plugins))
    argv = build_upgrade_packages(
        receipt,
        targets,
        color="never",
        overrides=str(overrides_path) if overrides_path is not None else None,
    )
    return UpdateReady(argv=argv, targets=targets, all_plugins=all_plugins)


def execute_update(
    plan: UpdateReady,
    *,
    run_fn: RunUvFn = run_uv,
    clock: ClockFn = time.monotonic,
) -> UpdateOutcome:
    """Run the ``uv`` upgrade for a ready plan and collect the outcome.

    Raises :class:`~sase.uv_tool.errors.UvToolError` if ``uv`` fails; the caller
    catches it.
    """
    start = clock()
    change_set = run_fn(plan.argv)
    elapsed = max(0.0, clock() - start)
    return UpdateOutcome(plan=plan, change_set=change_set, elapsed=elapsed)


def _resolve_update_target(
    receipt: ToolReceipt,
    query: str,
    *,
    load_fn: LoadFn,
    refresh: bool,
    offline: bool,
) -> Requirement | NotInstalled | UpdateUnknown:
    """Resolve *query* to an injected plugin, or explain why it is not one.

    Tries the receipt first (no catalog fetch) so an installed plugin — even a
    community one absent from the catalog — resolves directly. Only on a miss is
    the catalog loaded, to separate "known but not installed" from "unknown".
    """
    injected = match_injected(receipt, query)
    if injected is not None:
        return injected

    catalog = load_catalog(load_fn, refresh=refresh, offline=offline)
    entry = find_plugin(catalog, query)
    if entry is not None:
        return NotInstalled(entry.name)
    return UpdateUnknown(query, suggest_plugins(catalog, query))
