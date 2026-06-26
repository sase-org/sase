"""Console-free plugin install/update operations: plan, then execute.

This is the single source of truth for ``sase plugin install`` / ``update``
*resolution* and *orchestration*, extracted from the CLI handlers so any
frontend can drive the same domain behavior. Each operation is a **plan /
execute** split:

* ``plan_install`` / ``plan_update`` do all the impure-but-cheap work — probe the
  uv-tool install, read the receipt, resolve the ``<plugin>`` name, build the
  exact ``uv`` argv — and return a *typed outcome*. No ``uv`` mutation runs and
  nothing is printed. The ``*Ready`` outcome carries the argv, so a caller can
  show it verbatim as a confirm-preview (this *is* the ``--dry-run``).
* ``execute_install`` / ``execute_update`` take a ``*Ready`` plan and actually run
  ``uv``, returning a typed outcome with the change-set, elapsed time, and (for
  install) the entry-point groups the new plugin contributes.

The CLI handlers (:mod:`sase.plugins.cli_install` / :mod:`sase.plugins.cli_update`)
delegate to these functions and keep only rendering, JSON, and exit-code
mapping. The TUI Plugins tab calls the same functions: ``plan_*`` powers the
confirm-preview, ``execute_*`` runs inside a tracked background task.

Every impure dependency (the install probe, the catalog loader, the uv runner,
the installed-inventory lookup, the clock) stays injectable, so the whole layer
is unit-testable without a real uv install. Two failure modes — a catalog fetch
error and a malformed receipt — propagate as the existing
:class:`~sase.plugins.catalog.PluginCatalogError` /
:class:`~sase.uv_tool.errors.ReceiptError` exceptions rather than typed outcomes,
exactly as the CLI handled them before; callers catch and render them.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from sase.plugins.catalog import (
    PluginCatalog,
    PluginCatalogEntry,
    find_plugin,
    load_plugin_catalog,
    suggest_plugins,
)
from sase.plugins.installed import InstalledInfo, build_installed_index
from sase.uv_tool.commands import (
    build_install,
    build_uninstall,
    build_upgrade_packages,
)
from sase.uv_tool.detect import (
    NotUvToolInstall,
    UvToolInstall,
    probe_uv_tool_install,
)
from sase.uv_tool.errors import NotAUvToolInstallError
from sase.uv_tool.receipt import Requirement, ToolReceipt, load_receipt
from sase.uv_tool.runner import UvChangeSet, run_uv
from sase.version._utils import normalize_distribution_name

#: Spec source: resolved from the catalog, forced to git, or passed through.
SpecSource = Literal["catalog", "git", "passthrough"]

LoadFn = Callable[..., PluginCatalog]
ProbeFn = Callable[[], UvToolInstall | NotUvToolInstall]
RunUvFn = Callable[[list[str]], UvChangeSet]
InstalledIndexFn = Callable[[], dict[str, InstalledInfo]]
ClockFn = Callable[[], float]


# --------------------------------------------------------------------------- #
# Spec resolution (shared)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ResolvedSpec:
    """A ``<plugin>`` argument resolved to a uv install spec.

    *requirement* is what gets added to the reconstructed ``--with`` set;
    *display_name* is the short, friendly name for output; *source* records how
    the name was resolved (for the dry-run preview and the JSON payload).
    """

    requirement: Requirement
    display_name: str
    source: SpecSource

    @property
    def normalized_name(self) -> str:
        """PEP 503-normalized distribution name, for receipt matching."""
        return self.requirement.normalized_name


def resolve_install_spec(
    catalog: PluginCatalog, query: str, *, git: bool = False
) -> ResolvedSpec | None:
    """Resolve a ``<plugin>`` argument to a :class:`ResolvedSpec`, or ``None``.

    Resolution order (epic Phase 3):

    1. A raw requirement, git URL, or local path is passed through verbatim.
    2. Otherwise the name is looked up in the catalog: a hit installs from the
       distribution name (PyPI) by default, or from ``git+<repo url>`` when
       ``git`` is set.
    3. A catalog miss returns ``None`` so the caller can render ranked
       suggestions and exit non-zero.
    """
    stripped = query.strip()
    if not stripped:
        return None

    if _looks_like_raw_spec(stripped):
        requirement = Requirement.from_spec(stripped)
        return ResolvedSpec(
            requirement=requirement,
            display_name=requirement.name or stripped,
            source="passthrough",
        )

    entry = find_plugin(catalog, stripped)
    if entry is None:
        return None
    return _spec_from_entry(entry, git=git)


def _spec_from_entry(entry: PluginCatalogEntry, *, git: bool) -> ResolvedSpec:
    if git:
        # html_url (``https://github.com/owner/repo``) is git-cloneable as-is.
        requirement = Requirement.from_spec(f"git+{entry.url}")
        return ResolvedSpec(
            requirement=requirement, display_name=entry.name, source="git"
        )
    requirement = Requirement.from_spec(entry.repo)
    return ResolvedSpec(
        requirement=requirement, display_name=entry.name, source="catalog"
    )


def _looks_like_raw_spec(query: str) -> bool:
    """Whether *query* is a raw requirement / URL / path to pass through.

    A bare ``owner/repo`` catalog full name is *not* a path (it does not start
    with a path prefix), so it still resolves through the catalog.
    """
    if query.startswith("git+") or "://" in query:
        return True
    if query.startswith(("/", "./", "../", "~")) or query == ".":
        return True
    return any(op in query for op in ("==", ">=", "<=", "~=", "!=", ">", "<"))


def _load_catalog(load_fn: LoadFn, *, refresh: bool, offline: bool) -> PluginCatalog:
    """Load the catalog, forwarding ``offline`` only when it is set.

    The CLI never offered an offline install/update flag, and its long-standing
    test fakes accept only ``refresh``; forwarding ``offline`` unconditionally
    would break them. The default (online) path therefore preserves the exact
    historical ``load_fn(refresh=...)`` call, while the TUI — which passes the
    real :func:`~sase.plugins.catalog.load_plugin_catalog` — gets cache-first
    offline loads when it sets the flag.
    """
    if offline:
        return load_fn(refresh=refresh, offline=True)
    return load_fn(refresh=refresh)


# --------------------------------------------------------------------------- #
# Install: typed plan/outcome
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class NotUvTool:
    """sase is not a managed ``uv tool install sase`` — mutations are impossible.

    *error* carries the precise, already-rendered actionable message (the same
    one the CLI prints); display it verbatim.
    """

    error: NotAUvToolInstallError


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
class InstallOutcome:
    """The result of executing an :class:`InstallReady` plan."""

    plan: InstallReady
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

    catalog = _load_catalog(load_fn, refresh=refresh, offline=offline)
    spec = resolve_install_spec(catalog, query, git=git)
    if spec is None:
        return InstallNotFound(query, suggest_plugins(catalog, query))

    receipt = load_receipt(install.receipt_path)
    if receipt.is_injected(spec.normalized_name):
        return AlreadyInstalled(spec)

    argv = build_install(receipt, add=spec.requirement, color="never")
    return InstallReady(spec=spec, argv=argv)


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


# --------------------------------------------------------------------------- #
# Update: typed plan/outcome
# --------------------------------------------------------------------------- #


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
    as the CLI did before.

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

    argv = build_upgrade_packages(receipt, targets, color="never")
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
    injected = _match_injected(receipt, query)
    if injected is not None:
        return injected

    catalog = _load_catalog(load_fn, refresh=refresh, offline=offline)
    entry = find_plugin(catalog, query)
    if entry is not None:
        return NotInstalled(entry.name)
    return UpdateUnknown(query, suggest_plugins(catalog, query))


def _match_injected(receipt: ToolReceipt, query: str) -> Requirement | None:
    for candidate in _name_candidates(query):
        key = normalize_distribution_name(candidate)
        if not key:
            continue
        for plugin in receipt.deduped_injected_plugins():
            if plugin.normalized_name == key:
                return plugin
    return None


def _name_candidates(query: str) -> tuple[str, ...]:
    base = query.strip()
    short = base.split("/", 1)[1] if "/" in base else base
    candidates = [base, short]
    for value in (base, short):
        if value and not value.lower().startswith("sase-"):
            candidates.append(f"sase-{value}")
    return tuple(candidates)


def _short_display_name(dist_name: str) -> str:
    """Friendly short name for output: drop a leading ``sase-`` if present."""
    if dist_name.lower().startswith("sase-") and len(dist_name) > len("sase-"):
        return dist_name[len("sase-") :]
    return dist_name


# --------------------------------------------------------------------------- #
# Uninstall: typed plan/outcome
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AlreadyAbsent:
    """The plugin is known but not injected — uninstall is a no-op success.

    Removing something that is already gone is idempotent, so this is reported as
    a success (the CLI exits 0 and the TUI toasts neutrally), unlike update's
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
    injected = _match_injected(receipt, query)
    if injected is not None:
        argv = build_uninstall(receipt, remove=injected.normalized_name, color="never")
        return UninstallReady(
            requirement=injected,
            display_name=_short_display_name(injected.name),
            argv=argv,
        )

    catalog = _load_catalog(load_fn, refresh=refresh, offline=offline)
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


__all__ = [
    "AlreadyAbsent",
    "AlreadyInstalled",
    "InstallNotFound",
    "InstallOutcome",
    "InstallPlan",
    "InstallReady",
    "NoPlugins",
    "NotInstalled",
    "NotUvTool",
    "ResolvedSpec",
    "SpecSource",
    "UninstallOutcome",
    "UninstallPlan",
    "UninstallReady",
    "UninstallUnknown",
    "UpdateOutcome",
    "UpdatePlan",
    "UpdateReady",
    "UpdateUnknown",
    "execute_install",
    "execute_uninstall",
    "execute_update",
    "plan_install",
    "plan_uninstall",
    "plan_update",
    "resolve_install_spec",
]
