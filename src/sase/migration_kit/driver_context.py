"""Operation resolution and per-run context helpers for the migration driver.

TEMPORARY MODULE: deletion owner sase-x7.14.
"""

from __future__ import annotations

from pathlib import Path
import platform
import secrets
from typing import Any

from sase.core.paths import sase_home
from sase.core.time import local_now
from sase.migration_kit.catalog import OPERATION_SPECS
from sase.migration_kit.driver_outcome import MigrationCommandOutcome
from sase.migration_kit.operations import get_operation
from sase.migration_kit.operations.base import OperationContext


def operation_or_error(operation_name: str) -> Any:
    try:
        return get_operation(operation_name)
    except KeyError:
        names = ", ".join(spec.name for spec in OPERATION_SPECS)
        return MigrationCommandOutcome(
            False,
            command="operation",
            dry_run=True,
            message=f"unknown migration operation: {operation_name}",
            errors=(f"known operations: {names}",),
        )


def generate_run_id(operation_name: str) -> str:
    safe_operation = operation_name.replace("-", "_")
    timestamp = local_now().strftime("%Y%m%dT%H%M%S")
    return f"{platform.node() or 'host'}-{safe_operation}-{timestamp}-{secrets.token_hex(3)}"


def operation_context(
    *,
    run_id: str,
    root: Path | None,
    home: Path | None,
    backup_id: str | None,
) -> OperationContext:
    resolved_sase_home = (root or sase_home()).expanduser().resolve(strict=False)
    resolved_home = (
        home.expanduser().resolve(strict=False)
        if home is not None
        else resolved_sase_home.parent
    )
    return OperationContext(
        run_id=run_id,
        sase_home=resolved_sase_home,
        home=resolved_home,
        backup_id=backup_id,
    )


def resolve_catalog_root(root_label: str, context: OperationContext) -> Path:
    if root_label.startswith("~/.sase/"):
        return context.sase_home / root_label.removeprefix("~/.sase/")
    if root_label == "~/.sase":
        return context.sase_home
    if root_label.startswith("~/"):
        return context.home / root_label.removeprefix("~/")
    return Path(root_label).expanduser()
