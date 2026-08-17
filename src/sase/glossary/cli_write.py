"""Shared rendering and post-write regeneration for glossary add/delete."""

from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import sys
from typing import Literal, NoReturn
from collections.abc import Iterator

from rich.console import Console
from rich.table import Table
from rich.text import Text

from sase.cli_show_palette import PATH_COLOR, SECTION_COLOR
from sase.content_layout import resolve_project_config_write_path
from sase.core.glossary_facade import GlossaryDiagnostic
from sase.glossary.cli_common import GlossaryCliError
from sase.glossary.mutation import (
    GlossaryConflictError,
    GlossaryMutationError,
    GlossaryMutationOutcome,
    GlossaryValidationError,
)
from sase.glossary.resolution import GlossaryLookupError
from sase.glossary_config import GLOSSARY_CONFIG_KEY
from sase.xprompt.glossary_catalog import editor_glossary_catalog_for_project

GlossaryWriteFormat = Literal["json", "rich"]
GlossaryWriteOperation = Literal["add", "del"]

_INIT_FOLLOW_UP = "run `sase memory init`"


def emit_glossary_write_outcome(
    outcome: GlossaryMutationOutcome,
    *,
    operation: GlossaryWriteOperation,
    output_format: GlossaryWriteFormat,
    dry_run: bool,
    no_init: bool,
    command: str,
    console: Console | None = None,
) -> None:
    """Print a successful add/delete outcome in rich or JSON form."""
    initialized, init_warning = _maybe_regenerate(
        outcome, dry_run=dry_run, no_init=no_init
    )
    payload = _write_json_payload(
        outcome,
        operation=operation,
        dry_run=dry_run,
        initialized=initialized,
        init_warning=init_warning,
    )
    if output_format == "json":
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        target = console or Console()
        target.print(_build_write_table(outcome, operation=operation))
        if initialized:
            target.print(
                f"Regenerated agent instruction files for {outcome.project_name}."
            )
    if init_warning is not None:
        print(f"sase glossary {command}: warning: {init_warning}", file=sys.stderr)


def exit_glossary_write_error(
    command: str, exc: BaseException, *, project_ref: str | None = None
) -> NoReturn:
    """Print a write-command failure and exit non-zero."""
    if isinstance(exc, GlossaryValidationError):
        _print_validation_errors(command, exc, project_ref=project_ref)
        sys.exit(1)
    print(f"sase glossary {command}: {exc}", file=sys.stderr)
    sys.exit(1)


def write_error_types() -> tuple[type[BaseException], ...]:
    """Exceptions a glossary write command should report and exit on."""
    return (
        GlossaryCliError,
        GlossaryConflictError,
        GlossaryLookupError,
        GlossaryMutationError,
        GlossaryValidationError,
    )


def _write_json_payload(
    outcome: GlossaryMutationOutcome,
    *,
    operation: GlossaryWriteOperation,
    dry_run: bool,
    initialized: bool,
    init_warning: str | None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "aliases": list(outcome.aliases),
        "config_path": outcome.config_path,
        "definition": outcome.definition,
        "initialized": initialized,
        "operation": operation,
        "project": outcome.project_name,
        "term": outcome.term,
    }
    if operation == "add":
        payload["created_section"] = outcome.created_section
    else:
        payload["dry_run"] = dry_run
        payload["referenced_by"] = list(outcome.referenced_by)
        payload["restore_command"] = outcome.restore_command
    if init_warning is not None:
        payload["init_warning"] = init_warning
    return payload


def _build_write_table(
    outcome: GlossaryMutationOutcome, *, operation: GlossaryWriteOperation
) -> Table:
    verb = "ADDED" if operation == "add" else "DELETED"
    table = Table(
        title=Text(
            f"GLOSSARY  {verb}  {outcome.project_name}",
            style=f"bold {SECTION_COLOR}",
        ),
        show_header=False,
        box=None,
        padding=(0, 2, 0, 0),
    )
    table.add_column("Field", style="bold", no_wrap=True)
    table.add_column("Value")
    table.add_row("Term", outcome.term)
    table.add_row("Aliases", " · ".join(outcome.aliases) if outcome.aliases else "—")
    if operation == "del":
        table.add_row("Referenced by", _referenced_by_label(outcome.referenced_by))
    table.add_row("Config", Text(outcome.config_path, style=PATH_COLOR))
    if operation == "del":
        table.add_row("Restore", outcome.restore_command)
    return table


def _referenced_by_label(referenced_by: tuple[str, ...]) -> str:
    count = len(referenced_by)
    if count == 0:
        return "0"
    return f"{count} · " + " · ".join(referenced_by)


def _maybe_regenerate(
    outcome: GlossaryMutationOutcome, *, dry_run: bool, no_init: bool
) -> tuple[bool, str | None]:
    if dry_run or no_init:
        return False, None
    workspace = Path(outcome.workspace_dir)
    if not workspace.is_dir():
        return False, (
            "could not locate the project root to regenerate agent "
            f"instruction files; {_INIT_FOLLOW_UP}"
        )
    return _run_init_memory(workspace)


def _run_init_memory(workspace: Path) -> tuple[bool, str | None]:
    from sase.main.init_memory_handler import run_init_memory

    init_args = argparse.Namespace(
        check=False,
        diff=False,
        enable_project_memory=False,
        message=None,
        no_commit=True,
    )
    captured_out = StringIO()
    captured_err = StringIO()
    try:
        with (
            _working_directory(workspace),
            redirect_stdout(captured_out),
            redirect_stderr(captured_err),
        ):
            exit_code = run_init_memory(init_args)
    except Exception as exc:
        return False, (
            f"failed to regenerate agent instruction files ({exc}); {_INIT_FOLLOW_UP}"
        )
    if exit_code == 0:
        return True, None
    detail = captured_err.getvalue().strip() or captured_out.getvalue().strip()
    suffix = f": {detail.splitlines()[0]}" if detail else ""
    return False, (
        f"failed to regenerate agent instruction files{suffix}; {_INIT_FOLLOW_UP}"
    )


@contextmanager
def _working_directory(path: Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _print_validation_errors(
    command: str,
    exc: GlossaryValidationError,
    *,
    project_ref: str | None,
) -> None:
    config_path = _config_path_for_diagnostics(project_ref)
    if not exc.diagnostics:
        print(f"sase glossary {command}: {exc}", file=sys.stderr)
        return
    for item in exc.diagnostics:
        print(_format_diagnostic(command, item, config_path), file=sys.stderr)


def _format_diagnostic(
    command: str, item: GlossaryDiagnostic, config_path: str | None
) -> str:
    key_path = _diagnostic_key_path(item.path)
    parts = [f"sase glossary {command}:"]
    if config_path:
        parts.append(config_path)
    parts.append(key_path)
    parts.append(f"{item.code}: {item.message}")
    return " ".join(parts)


def _diagnostic_key_path(path: str | None) -> str:
    if not path:
        return "memory.glossary"
    if path == GLOSSARY_CONFIG_KEY:
        return "memory.glossary"
    if path.startswith(f"{GLOSSARY_CONFIG_KEY}."):
        return f"memory.glossary{path.removeprefix(GLOSSARY_CONFIG_KEY)}"
    return path


def _config_path_for_diagnostics(project_ref: str | None) -> str | None:
    result = editor_glossary_catalog_for_project(project_ref)
    if result.catalog is not None:
        return str(result.catalog.config_path)
    if result.project is not None:
        return str(resolve_project_config_write_path(result.project.workspace_dir))
    return None


__all__ = [
    "emit_glossary_write_outcome",
    "exit_glossary_write_error",
    "write_error_types",
]
