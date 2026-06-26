"""Handler for the top-level ``sase update`` command.

The CLI-facing seam on top of the Phase 1 ``uv tool`` engine. The flow follows
the epic's decisions: detect a managed ``uv tool install sase`` (*D4*); on
failure, render the typed, actionable error and exit non-zero; otherwise run
``uv tool upgrade sase`` (*D3*) — re-resolving sase core and every plugin in one
shot — parse the change set, and render it. ``-n|--dry-run`` previews the exact
uv argv and package set without executing (*D5*); ``-j|--json`` emits a stable,
sorted payload; ``-q|--quiet`` collapses output to a one-line summary.

Every impure dependency (the install probe, the uv runner, the version lookup,
the clock) is injectable, so the whole handler is unit-testable without a real
uv install.
"""

from __future__ import annotations

import argparse
import importlib.metadata as importlib_metadata
import json
import time
from collections.abc import Callable
from typing import Any

from rich.console import Console

from sase.uv_tool.commands import build_upgrade_all
from sase.uv_tool.detect import (
    NotUvToolInstall,
    UvToolInstall,
    probe_uv_tool_install,
)
from sase.uv_tool.errors import NotAUvToolInstallError, ReceiptError, UvToolError
from sase.uv_tool.receipt import ToolReceipt, load_receipt
from sase.uv_tool.render import (
    PlannedPackage,
    UpdateOutcome,
    UpdateSummary,
    render_update_dry_run,
    render_update_result,
    render_uv_tool_error,
    summarize_update,
)
from sase.uv_tool.runner import UvChangeSet, run_uv

#: Bump when the ``-j|--json`` payload shape changes incompatibly.
UPDATE_JSON_SCHEMA_VERSION = 1

ProbeFn = Callable[[], UvToolInstall | NotUvToolInstall]
RunUvFn = Callable[[list[str]], UvChangeSet]
VersionFn = Callable[[str], str | None]
ClockFn = Callable[[], float]


def _installed_version(name: str) -> str | None:
    """Return the installed version of distribution *name*, or ``None``."""
    try:
        return importlib_metadata.version(name)
    except importlib_metadata.PackageNotFoundError:
        return None
    except Exception:  # noqa: BLE001 — version display must never crash the run.
        return None


def handle_update_command(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
    err_console: Console | None = None,
    probe_fn: ProbeFn = probe_uv_tool_install,
    run_fn: RunUvFn = run_uv,
    version_fn: VersionFn = _installed_version,
    clock: ClockFn = time.monotonic,
) -> int:
    """Run ``sase update``; return the process exit code."""
    as_json = bool(getattr(args, "json", False))
    dry_run = bool(getattr(args, "dry_run", False))
    quiet = bool(getattr(args, "quiet", False))
    out = console or Console()
    err = err_console or Console(stderr=True)

    install = probe_fn()
    if isinstance(install, NotUvToolInstall):
        return _fail(NotAUvToolInstallError(install), as_json=as_json, err=err)

    if dry_run:
        return _handle_dry_run(
            install, as_json=as_json, out=out, err=err, version_fn=version_fn
        )

    argv = build_upgrade_all(color="never")
    use_spinner = not as_json and not quiet and out.is_terminal
    start = clock()
    try:
        if use_spinner:
            with out.status("Upgrading sase and its plugins via uv…", spinner="dots"):
                change_set = run_fn(argv)
        else:
            change_set = run_fn(argv)
    except UvToolError as exc:
        return _fail(exc, as_json=as_json, err=err)
    elapsed = max(0.0, clock() - start)

    summary = summarize_update(
        change_set, _try_load_receipt(install), current_version=version_fn
    )

    if as_json:
        print(
            json.dumps(_result_json(argv, summary, elapsed), indent=2, sort_keys=True)
        )
        return 0

    render_update_result(summary, elapsed=elapsed, quiet=quiet, console=out)
    return 0


def _handle_dry_run(
    install: UvToolInstall,
    *,
    as_json: bool,
    out: Console,
    err: Console,
    version_fn: VersionFn,
) -> int:
    argv = build_upgrade_all(color="never")
    try:
        receipt = load_receipt(install.receipt_path)
    except ReceiptError as exc:
        return _fail(exc, as_json=as_json, err=err)

    packages = _planned_packages(receipt, version_fn)
    if as_json:
        print(json.dumps(_dry_run_json(argv, packages), indent=2, sort_keys=True))
        return 0

    render_update_dry_run(argv, packages, console=out)
    return 0


def _fail(error: UvToolError, *, as_json: bool, err: Console) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": UPDATE_JSON_SCHEMA_VERSION,
                    "error": str(error),
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        render_uv_tool_error(str(error), console=err)
    return 1


def _try_load_receipt(install: UvToolInstall) -> ToolReceipt | None:
    """Load the receipt for the package set, tolerating a parse failure.

    The upgrade has already succeeded by this point; a malformed receipt should
    only degrade the pretty "already current" cross-reference, never fail the
    command.
    """
    try:
        return load_receipt(install.receipt_path)
    except ReceiptError:
        return None


def _planned_packages(
    receipt: ToolReceipt, version_fn: VersionFn
) -> tuple[PlannedPackage, ...]:
    packages = [
        PlannedPackage(
            name=receipt.primary.name,
            role="primary",
            current_version=version_fn(receipt.primary.name),
        )
    ]
    packages += [
        PlannedPackage(
            name=plugin.name,
            role="plugin",
            current_version=version_fn(plugin.name),
        )
        for plugin in receipt.injected_plugins()
    ]
    return tuple(packages)


def _result_json(
    argv: list[str], summary: UpdateSummary, elapsed: float
) -> dict[str, Any]:
    return {
        "schema_version": UPDATE_JSON_SCHEMA_VERSION,
        "dry_run": False,
        "command": list(argv),
        "changed": summary.changed,
        "elapsed_seconds": round(elapsed, 3),
        "counts": {
            "updated": len(summary.updated),
            "already_current": len(summary.already_current),
            "removed": len(summary.removed),
        },
        "packages": [_outcome_json(outcome) for outcome in summary.outcomes],
    }


def _outcome_json(outcome: UpdateOutcome) -> dict[str, Any]:
    return {
        "name": outcome.name,
        "role": outcome.role,
        "kind": outcome.kind.value,
        "old_version": outcome.old_version,
        "new_version": outcome.new_version,
    }


def _dry_run_json(
    argv: list[str], packages: tuple[PlannedPackage, ...]
) -> dict[str, Any]:
    return {
        "schema_version": UPDATE_JSON_SCHEMA_VERSION,
        "dry_run": True,
        "command": list(argv),
        "packages": [
            {
                "name": package.name,
                "role": package.role,
                "current_version": package.current_version,
            }
            for package in packages
        ],
    }


__all__ = [
    "UPDATE_JSON_SCHEMA_VERSION",
    "handle_update_command",
]
