"""Install planning and execution for SASE plugins."""

from __future__ import annotations

import time
from dataclasses import dataclass

from sase.plugins.catalog import (
    PluginCatalogEntry,
    load_plugin_catalog,
    suggest_plugins,
)
from sase.plugins.installed import build_installed_index
from sase.uv_tool.commands import build_install, build_install_many
from sase.uv_tool.detect import NotUvToolInstall, probe_uv_tool_install
from sase.uv_tool.errors import NotAUvToolInstallError
from sase.uv_tool.overrides import write_editable_overrides
from sase.uv_tool.preflight import ephemeral_install_source_error
from sase.uv_tool.receipt import load_receipt
from sase.uv_tool.runner import UvChangeSet, run_uv

from ._operations_common import (
    ClockFn,
    InstalledIndexFn,
    LoadFn,
    NotUvTool,
    ProbeFn,
    ResolvedSpec,
    RunUvFn,
    load_catalog,
    resolve_install_spec,
)


@dataclass(frozen=True)
class InstallNotFound:
    """The ``<plugin>`` name matched nothing in the catalog."""

    query: str
    suggestions: tuple[PluginCatalogEntry, ...]


@dataclass(frozen=True)
class AlreadyInstalled:
    """The plugin is already injected into sase's uv environment (idempotent)."""

    spec: ResolvedSpec


@dataclass(frozen=True)
class InstallReady:
    """Resolved and ready to install: *argv* is the exact ``uv`` command."""

    spec: ResolvedSpec
    argv: list[str]


#: A planned install: one of these four typed outcomes.
InstallPlan = NotUvTool | InstallNotFound | AlreadyInstalled | InstallReady


@dataclass(frozen=True)
class InstallSkipped:
    """A batch-install input that could not be included in the uv operation."""

    query: str
    reason: str
    suggestions: tuple[PluginCatalogEntry, ...] = ()


@dataclass(frozen=True)
class InstallManyNothing:
    """A batch install where every requested plugin was skipped."""

    skipped: tuple[InstallSkipped, ...]


@dataclass(frozen=True)
class InstallManyReady:
    """Resolved batch install: *argv* injects every target in one uv command."""

    specs: tuple[ResolvedSpec, ...]
    argv: list[str]
    skipped: tuple[InstallSkipped, ...] = ()


#: A planned batch install.
InstallManyPlan = NotUvTool | InstallManyNothing | InstallManyReady


@dataclass(frozen=True)
class InstallOutcome:
    """The result of executing an :class:`InstallReady` plan."""

    plan: InstallReady
    change_set: UvChangeSet
    groups: tuple[str, ...]
    elapsed: float


@dataclass(frozen=True)
class InstallManyOutcome:
    """The result of executing an :class:`InstallManyReady` plan."""

    plan: InstallManyReady
    change_set: UvChangeSet
    groups: tuple[str, ...]
    elapsed: float


def plan_install(
    query: str,
    *,
    git: bool = False,
    refresh: bool = False,
    offline: bool = False,
    load_fn: LoadFn = load_plugin_catalog,
    probe_fn: ProbeFn = probe_uv_tool_install,
) -> InstallPlan:
    """Plan ``sase plugin install <query>`` without running ``uv``.

    Probes the uv-tool install, loads the catalog, resolves *query* to a uv
    spec, reads the receipt, and either reports a terminal outcome
    (:class:`NotUvTool`, :class:`InstallNotFound`, :class:`AlreadyInstalled`) or
    returns an :class:`InstallReady` carrying the exact ``uv`` argv. Raises
    :class:`~sase.plugins.catalog.PluginCatalogError` if the catalog cannot be
    loaded and :class:`~sase.uv_tool.errors.ReceiptError` if the receipt is
    unreadable — callers catch and render those.
    """
    install = probe_fn()
    if isinstance(install, NotUvToolInstall):
        return NotUvTool(NotAUvToolInstallError(install))

    catalog = load_catalog(load_fn, refresh=refresh, offline=offline)
    spec = resolve_install_spec(catalog, query, git=git)
    if spec is None:
        return InstallNotFound(query, suggest_plugins(catalog, query))
    if (error := ephemeral_install_source_error(spec.requirement)) is not None:
        return NotUvTool(error)

    receipt = load_receipt(install.receipt_path)
    if receipt.is_injected(spec.normalized_name):
        return AlreadyInstalled(spec)

    recon = receipt.reconstruct(add=spec.requirement)
    overrides_path = write_editable_overrides((recon.primary, *recon.plugins))
    argv = build_install(
        receipt,
        add=spec.requirement,
        color="never",
        overrides=str(overrides_path) if overrides_path is not None else None,
    )
    return InstallReady(spec=spec, argv=argv)


def plan_install_many(
    queries: list[str] | tuple[str, ...],
    *,
    refresh: bool = False,
    offline: bool = False,
    load_fn: LoadFn = load_plugin_catalog,
    probe_fn: ProbeFn = probe_uv_tool_install,
) -> InstallManyPlan:
    """Plan a batch install as one combined ``uv`` operation.

    Each input is resolved through the catalog using the default index source.
    Unknown or already-injected plugins are reported in ``skipped``; resolvable
    not-yet-injected plugins are added to one reconstructed receipt install
    argv. No mutation runs here.
    """
    install = probe_fn()
    if isinstance(install, NotUvToolInstall):
        return NotUvTool(NotAUvToolInstallError(install))

    catalog = load_catalog(load_fn, refresh=refresh, offline=offline)
    receipt = load_receipt(install.receipt_path)
    specs: list[ResolvedSpec] = []
    skipped: list[InstallSkipped] = []
    selected: set[str] = set()

    for query in queries:
        spec = resolve_install_spec(catalog, query, git=False)
        if spec is None:
            skipped.append(
                InstallSkipped(
                    query=query,
                    reason="not found",
                    suggestions=suggest_plugins(catalog, query),
                )
            )
            continue
        if receipt.is_injected(spec.normalized_name):
            skipped.append(InstallSkipped(query=query, reason="already installed"))
            continue
        if spec.normalized_name in selected:
            skipped.append(InstallSkipped(query=query, reason="duplicate"))
            continue
        if (error := ephemeral_install_source_error(spec.requirement)) is not None:
            skipped.append(InstallSkipped(query=query, reason=str(error)))
            continue
        selected.add(spec.normalized_name)
        specs.append(spec)

    if not specs:
        return InstallManyNothing(skipped=tuple(skipped))

    recon = receipt.reconstruct(adds=(spec.requirement for spec in specs))
    overrides_path = write_editable_overrides((recon.primary, *recon.plugins))
    argv = build_install_many(
        receipt,
        add=(spec.requirement for spec in specs),
        color="never",
        overrides=str(overrides_path) if overrides_path is not None else None,
    )
    return InstallManyReady(
        specs=tuple(specs),
        argv=argv,
        skipped=tuple(skipped),
    )


def execute_install(
    plan: InstallReady,
    *,
    run_fn: RunUvFn = run_uv,
    installed_index_fn: InstalledIndexFn = build_installed_index,
    clock: ClockFn = time.monotonic,
) -> InstallOutcome:
    """Run the ``uv`` install for a ready plan and collect the outcome.

    Raises :class:`~sase.uv_tool.errors.UvToolError` if ``uv`` fails; the caller
    catches it. The entry-point-group lookup is best-effort and never raises.
    """
    start = clock()
    change_set = run_fn(plan.argv)
    elapsed = max(0.0, clock() - start)
    groups = _installed_groups(installed_index_fn, plan.spec.normalized_name)
    return InstallOutcome(
        plan=plan, change_set=change_set, groups=groups, elapsed=elapsed
    )


def execute_install_many(
    plan: InstallManyReady,
    *,
    run_fn: RunUvFn = run_uv,
    installed_index_fn: InstalledIndexFn = build_installed_index,
    clock: ClockFn = time.monotonic,
) -> InstallManyOutcome:
    """Run the combined ``uv`` install for a ready batch plan."""
    start = clock()
    change_set = run_fn(plan.argv)
    elapsed = max(0.0, clock() - start)
    groups = _installed_groups_many(installed_index_fn, plan.specs)
    return InstallManyOutcome(
        plan=plan,
        change_set=change_set,
        groups=groups,
        elapsed=elapsed,
    )


def _installed_groups(
    installed_index_fn: InstalledIndexFn, normalized_name: str
) -> tuple[str, ...]:
    """Best-effort entry-point groups the freshly-installed plugin contributes.

    Looked up from a freshly-built installed index after the install. Must never
    fail the command, so any error degrades to "no groups known".
    """
    try:
        index = installed_index_fn()
    except Exception:  # noqa: BLE001 — group display must never crash the run.
        return ()
    info = index.get(normalized_name)
    return info.entry_point_groups if info is not None else ()


def _installed_groups_many(
    installed_index_fn: InstalledIndexFn, specs: tuple[ResolvedSpec, ...]
) -> tuple[str, ...]:
    """Best-effort aggregate entry-point groups for a batch install."""
    try:
        index = installed_index_fn()
    except Exception:  # noqa: BLE001 — group display must never crash the run.
        return ()
    groups: list[str] = []
    seen: set[str] = set()
    for spec in specs:
        info = index.get(spec.normalized_name)
        if info is None:
            continue
        for group in info.entry_point_groups:
            if group not in seen:
                seen.add(group)
                groups.append(group)
    return tuple(groups)
