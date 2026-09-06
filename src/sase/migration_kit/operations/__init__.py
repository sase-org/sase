"""Operation registry for the temporary migration kit.

TEMPORARY MODULE: deletion owner sase-x7.14.
"""

from __future__ import annotations

from sase.migration_kit.operations.base import MigrationOperation
from sase.migration_kit.operations.import_purge import ImportPurgeOperation
from sase.migration_kit.operations.lock_residue import LockResidueOperation
from sase.migration_kit.operations.procs_residue import ProcsResidueOperation
from sase.migration_kit.operations.state_residue import StateResidueOperation

OPERATIONS: tuple[MigrationOperation, ...] = (
    ImportPurgeOperation(),
    LockResidueOperation(),
    ProcsResidueOperation(),
    StateResidueOperation(),
)

OPERATIONS_BY_NAME = {operation.spec.name: operation for operation in OPERATIONS}


def get_operation(name: str) -> MigrationOperation:
    """Return the shipped operation named *name*."""
    return OPERATIONS_BY_NAME[name]


__all__ = ["OPERATIONS", "OPERATIONS_BY_NAME", "get_operation"]
