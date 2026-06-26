"""Orchestration for ``sase plugin install <plugin>``.

This is the CLI-facing seam joining the plugin catalog (Phase 1/2) to the shared
``uv tool`` engine (Phase 1 of the ``sase update`` epic). The flow follows the
epic's decisions: detect a managed ``uv tool install sase`` (*D4*); resolve the
``<plugin>`` name to a uv install spec; read sase's uv receipt as the source of
truth for the injected set (*D2*); if the plugin is already injected, render an
idempotent message and exit success; otherwise re-run ``uv tool install`` with
the **full** reconstructed ``--with`` set plus the new plugin (finding #2) and
render the result. ``-n|--dry-run`` previews the exact uv argv without executing
(*D5*); ``-j|--json`` emits a stable payload.

Every impure dependency (the install probe, the catalog loader, the uv runner,
the installed-inventory lookup) is injectable, so the whole handler is
unit-testable without a real uv install.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from rich.console import Console

from sase.plugins.catalog import (
    PluginCatalog,
    PluginCatalogEntry,
    PluginCatalogError,
    find_plugin,
    load_plugin_catalog,
    suggest_plugins,
)
from sase.plugins.installed import InstalledInfo, build_installed_index
from sase.plugins.render import (
    render_install_already_installed,
    render_install_dry_run,
    render_install_result,
    render_show_not_found,
)
from sase.uv_tool.commands import build_install
from sase.uv_tool.detect import (
    NotUvToolInstall,
    UvToolInstall,
    probe_uv_tool_install,
)
from sase.uv_tool.errors import NotAUvToolInstallError, ReceiptError, UvToolError
from sase.uv_tool.receipt import Requirement, load_receipt
from sase.uv_tool.render import render_uv_tool_error
from sase.uv_tool.runner import ChangeKind, UvChangeSet, run_uv
from sase.version._utils import normalize_distribution_name

#: Bump when the ``-j|--json`` payload shape changes incompatibly.
INSTALL_JSON_SCHEMA_VERSION = 1

#: Spec source: resolved from the catalog, forced to git, or passed through.
SpecSource = Literal["catalog", "git", "passthrough"]

LoadFn = Callable[..., PluginCatalog]
ProbeFn = Callable[[], UvToolInstall | NotUvToolInstall]
RunUvFn = Callable[[list[str]], UvChangeSet]
InstalledIndexFn = Callable[[], dict[str, InstalledInfo]]
ClockFn = Callable[[], float]


@dataclass(frozen=True)
class _ResolvedSpec:
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


def _resolve_install_spec(
    catalog: PluginCatalog, query: str, *, git: bool = False
) -> _ResolvedSpec | None:
    """Resolve a ``<plugin>`` argument to a :class:`_ResolvedSpec`, or ``None``.

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
        return _ResolvedSpec(
            requirement=requirement,
            display_name=requirement.name or stripped,
            source="passthrough",
        )

    entry = find_plugin(catalog, stripped)
    if entry is None:
        return None
    return _spec_from_entry(entry, git=git)


def _spec_from_entry(entry: PluginCatalogEntry, *, git: bool) -> _ResolvedSpec:
    if git:
        # html_url (``https://github.com/owner/repo``) is git-cloneable as-is.
        requirement = Requirement.from_spec(f"git+{entry.url}")
        return _ResolvedSpec(
            requirement=requirement, display_name=entry.name, source="git"
        )
    requirement = Requirement.from_spec(entry.repo)
    return _ResolvedSpec(
        requirement=requirement, display_name=entry.name, source="catalog"
    )


def handle_plugin_install_command(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
    err_console: Console | None = None,
    load_fn: LoadFn = load_plugin_catalog,
    probe_fn: ProbeFn = probe_uv_tool_install,
    run_fn: RunUvFn = run_uv,
    installed_index_fn: InstalledIndexFn = build_installed_index,
    clock: ClockFn = time.monotonic,
) -> int:
    """Run ``sase plugin install <plugin>``; return the process exit code."""
    query = str(getattr(args, "plugin", "") or "")
    git = bool(getattr(args, "git", False))
    refresh = bool(getattr(args, "refresh", False))
    dry_run = bool(getattr(args, "dry_run", False))
    as_json = bool(getattr(args, "json", False))
    out = console or Console()
    err = err_console or Console(stderr=True)

    install = probe_fn()
    if isinstance(install, NotUvToolInstall):
        return _fail(NotAUvToolInstallError(install), as_json=as_json, err=err)

    try:
        catalog = load_fn(refresh=refresh)
    except PluginCatalogError as exc:
        return _fail_catalog(exc, as_json=as_json, err=err)

    resolved = _resolve_install_spec(catalog, query, git=git)
    if resolved is None:
        return _not_found(catalog, query, as_json=as_json, err=err)

    try:
        receipt = load_receipt(install.receipt_path)
    except ReceiptError as exc:
        return _fail(exc, as_json=as_json, err=err)

    if receipt.is_injected(resolved.normalized_name):
        return _already_installed(resolved, as_json=as_json, out=out)

    argv = build_install(receipt, add=resolved.requirement, color="never")
    if dry_run:
        return _dry_run(resolved, argv, as_json=as_json, out=out)

    use_spinner = not as_json and out.is_terminal
    start = clock()
    try:
        if use_spinner:
            with out.status(
                f"Installing {resolved.display_name} via uv…", spinner="dots"
            ):
                change_set = run_fn(argv)
        else:
            change_set = run_fn(argv)
    except UvToolError as exc:
        return _fail(exc, as_json=as_json, err=err)
    elapsed = max(0.0, clock() - start)

    groups = _installed_groups(installed_index_fn, resolved.normalized_name)
    if as_json:
        print(
            json.dumps(
                _result_json(resolved, argv, change_set, groups, elapsed),
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    render_install_result(
        dist_name=resolved.requirement.name,
        short_name=resolved.display_name,
        change_set=change_set,
        groups=groups,
        elapsed=elapsed,
        console=out,
    )
    return 0


def _already_installed(resolved: _ResolvedSpec, *, as_json: bool, out: Console) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": INSTALL_JSON_SCHEMA_VERSION,
                    "dry_run": False,
                    "already_installed": True,
                    "plugin": resolved.display_name,
                    "distribution": resolved.requirement.name,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    render_install_already_installed(
        dist_name=resolved.requirement.name,
        short_name=resolved.display_name,
        console=out,
    )
    return 0


def _dry_run(
    resolved: _ResolvedSpec, argv: list[str], *, as_json: bool, out: Console
) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": INSTALL_JSON_SCHEMA_VERSION,
                    "dry_run": True,
                    "command": list(argv),
                    "plugin": resolved.display_name,
                    "distribution": resolved.requirement.name,
                    "source": resolved.source,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    render_install_dry_run(
        argv=argv,
        short_name=resolved.display_name,
        source=resolved.source,
        console=out,
    )
    return 0


def _not_found(
    catalog: PluginCatalog,
    query: str,
    *,
    as_json: bool,
    err: Console,
) -> int:
    suggestions = suggest_plugins(catalog, query)
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": INSTALL_JSON_SCHEMA_VERSION,
                    "found": False,
                    "query": query,
                    "suggestions": [entry.name for entry in suggestions],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    render_show_not_found(query, suggestions, console=err)
    return 1


def _fail(error: UvToolError, *, as_json: bool, err: Console) -> int:
    if as_json:
        print(
            json.dumps(
                {"schema_version": INSTALL_JSON_SCHEMA_VERSION, "error": str(error)},
                indent=2,
                sort_keys=True,
            )
        )
    else:
        render_uv_tool_error(str(error), console=err)
    return 1


def _fail_catalog(error: PluginCatalogError, *, as_json: bool, err: Console) -> int:
    if as_json:
        print(
            json.dumps(
                {"schema_version": INSTALL_JSON_SCHEMA_VERSION, "error": str(error)},
                indent=2,
                sort_keys=True,
            )
        )
    else:
        err.print(str(error))
    return 1


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


def _result_json(
    resolved: _ResolvedSpec,
    argv: list[str],
    change_set: UvChangeSet,
    groups: tuple[str, ...],
    elapsed: float,
) -> dict[str, Any]:
    change = change_set.get(resolved.requirement.name)
    return {
        "schema_version": INSTALL_JSON_SCHEMA_VERSION,
        "dry_run": False,
        "command": list(argv),
        "plugin": resolved.display_name,
        "distribution": resolved.requirement.name,
        "source": resolved.source,
        "version": change.new_version if change is not None else None,
        "entry_point_groups": list(groups),
        "elapsed_seconds": round(elapsed, 3),
        "dependencies_changed": sum(
            1
            for c in change_set.changes
            if normalize_distribution_name(c.name) != resolved.normalized_name
            and c.kind is not ChangeKind.UNCHANGED
        ),
    }


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


__all__ = [
    "INSTALL_JSON_SCHEMA_VERSION",
    "handle_plugin_install_command",
]
