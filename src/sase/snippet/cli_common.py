"""Shared project resolution, JSON shaping, and error exits for snippet CLI."""

from __future__ import annotations

from typing import Literal, NoReturn
import json
import sys

from sase.core.snippet_catalog_facade import SnippetCall, SnippetDiagnostic
from sase.snippet.catalog import load_snippet_catalog, resolve_snippet_catalog_context
from sase.snippet.lookup import SnippetLookupError
from sase.snippet.models import (
    SnippetCatalog,
    SnippetEntry,
    SnippetLayerDiagnostic,
    SnippetMutationOutcome,
    SnippetSourceContribution,
)
from sase.snippet.mutation import (
    SnippetConflictError,
    SnippetMutationError,
    SnippetReadOnlyError,
    SnippetValidationError,
)

SnippetWriteFormat = Literal["json", "rich"]
SnippetListFormat = Literal["json", "names", "table"]
SnippetShowFormat = Literal["json", "markdown", "rich"]

_EXIT_LOOKUP = 1
_EXIT_CONTEXT = 2
_EXIT_WRITE = 3


class SnippetCliError(RuntimeError):
    """Raised when a project cannot be resolved for a snippet CLI command."""


def load_snippet_cli_catalog(project_ref: str | None) -> SnippetCatalog:
    """Load the catalog for *project_ref*, or the workspace-inferred project.

    Raises :class:`SnippetCliError` when ``-p/--project`` names a project
    that cannot be resolved. A missing ``-p`` still loads the CWD/default
    layers even when no enabled project is registered.
    """
    if project_ref:
        context = resolve_snippet_catalog_context(project_ref)
        if context.key is None:
            raise SnippetCliError(f"no such project: {project_ref}")
    return load_snippet_catalog(project_ref)


def catalog_project_name(catalog: SnippetCatalog) -> str:
    """Return the user-facing project name for *catalog*."""
    return catalog.context.name or ""


def write_json(payload: object) -> None:
    """Dump *payload* as deterministic, color-free JSON on stdout."""
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def snippet_entry_json(entry: SnippetEntry) -> dict[str, object]:
    """Return the stable JSON object for one catalog entry."""
    return {
        "aliases": list(entry.aliases),
        "composed_template": entry.composed_template,
        "contributions": [
            _snippet_contribution_json(item) for item in entry.contributions
        ],
        "diagnostics": [_snippet_diagnostic_json(item) for item in entry.diagnostics],
        "origin": _snippet_contribution_json(entry.origin),
        "raw_template": entry.raw_template,
        "relations": {
            "calls": [_snippet_call_json(call) for call in entry.relations.calls],
            "inbound": list(entry.relations.inbound),
            "outbound": list(entry.relations.outbound),
        },
        "trigger": entry.trigger,
    }


def _snippet_contribution_json(item: SnippetSourceContribution) -> dict[str, object]:
    """Return the stable JSON object for one source contribution."""
    return {
        "description": item.description,
        "display_path": item.display_path,
        "kind": item.kind,
        "path": item.path,
        "shadowed_by": item.shadowed_by,
        "template": item.template,
        "trigger": item.trigger,
        "writable": item.writable,
        "xprompt_name": item.xprompt_name,
    }


def _snippet_call_json(call: SnippetCall) -> dict[str, object]:
    """Return the stable JSON object for one authored snippet call."""
    return {
        "authored_target": call.authored_target,
        "canonical_target": call.canonical_target,
        "positional_args": list(call.positional_args),
        "span": {"end": call.span.end, "start": call.span.start},
        "status": call.status,
    }


def _snippet_diagnostic_json(item: SnippetDiagnostic) -> dict[str, object]:
    """Return the stable JSON object for one Rust snippet diagnostic."""
    span = None
    if item.span is not None:
        span = {"end": item.span.end, "start": item.span.start}
    return {
        "code": item.code,
        "cycle": None if item.cycle is None else list(item.cycle),
        "message": item.message,
        "span": span,
        "target": item.target,
        "trigger": item.trigger,
    }


def snippet_layer_diagnostic_json(
    item: SnippetLayerDiagnostic,
) -> dict[str, object]:
    """Return the stable JSON object for one config/xprompt layer diagnostic."""
    return {
        "layer": item.layer,
        "message": item.message,
        "path": item.path,
        "trigger": item.trigger,
    }


def snippet_write_json(outcome: SnippetMutationOutcome) -> dict[str, object]:
    """Return the stable JSON object for an add or delete outcome."""
    revealed = (
        None if outcome.revealed is None else snippet_entry_json(outcome.revealed)
    )
    return {
        "action": outcome.action,
        "affected_backlinks": list(outcome.affected_backlinks),
        "apply_target": outcome.apply_target,
        "content_digest": outcome.content_digest,
        "created": outcome.created,
        "dry_run": outcome.dry_run,
        "project": outcome.project_name,
        "read_path": outcome.read_path,
        "removed_paths": list(outcome.removed_paths),
        "restore_command": outcome.restore_command,
        "revealed": revealed,
        "source_kind": outcome.source_kind,
        "template": outcome.template,
        "trigger": outcome.trigger,
        "via_chezmoi": outcome.via_chezmoi,
        "write_path": outcome.write_path,
    }


def write_error_types() -> tuple[type[BaseException], ...]:
    """Exceptions a snippet write command should report and exit on."""
    return (
        SnippetCliError,
        SnippetConflictError,
        SnippetLookupError,
        SnippetMutationError,
        SnippetReadOnlyError,
        SnippetValidationError,
    )


def exit_snippet_error(command: str, exc: BaseException) -> NoReturn:
    """Print a command-prefixed failure and exit with a distinguishing code."""
    prefix = f"sase snippet {command}"
    if isinstance(exc, SnippetValidationError):
        _print_validation_errors(prefix, exc)
        sys.exit(_EXIT_WRITE)
    print(f"{prefix}: {exc}", file=sys.stderr)
    if isinstance(exc, SnippetCliError):
        sys.exit(_EXIT_CONTEXT)
    if isinstance(exc, SnippetLookupError):
        sys.exit(_EXIT_LOOKUP)
    sys.exit(_EXIT_WRITE)


def _print_validation_errors(prefix: str, exc: SnippetValidationError) -> None:
    if not exc.diagnostics:
        print(f"{prefix}: {exc}", file=sys.stderr)
        return
    for item in exc.diagnostics:
        print(f"{prefix}: {item.code}: {item.message}", file=sys.stderr)


__all__ = [
    "SnippetCliError",
    "SnippetListFormat",
    "SnippetShowFormat",
    "SnippetWriteFormat",
    "catalog_project_name",
    "exit_snippet_error",
    "load_snippet_cli_catalog",
    "snippet_entry_json",
    "snippet_layer_diagnostic_json",
    "snippet_write_json",
    "write_error_types",
    "write_json",
]
