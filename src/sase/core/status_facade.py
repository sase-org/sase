"""sase.core facade for status transitions and pure status field helpers.

Phase 0A: thin wrappers around :mod:`sase.status_state_machine`. Phase 0B
will route the public functions through these dispatched entry points.

The transition entry point performs disk IO (it acquires a lock and rewrites
the project file). It is therefore not a pure-core operation in the strict
sense, but it sits at the same seam as parser/query: a single Rust-bindable
function over inputs the host has already gathered.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.core.backend import dispatch
from sase.status_state_machine.field_updates import (
    apply_status_update_python,
    read_status_from_lines_python,
)
from sase.status_state_machine.siblings import SiblingRevertResult
from sase.status_state_machine.transitions import transition_changespec_status_python

if TYPE_CHECKING:
    from rich.console import Console


def read_status_from_lines(lines: list[str], changespec_name: str) -> str | None:
    """Read the STATUS field from raw project-file lines via the active backend."""
    return dispatch(
        operation="read_status_from_lines",
        python_impl=read_status_from_lines_python,
        args=(lines, changespec_name),
    )


def apply_status_update(lines: list[str], changespec_name: str, new_status: str) -> str:
    """Return updated file content with the STATUS line rewritten."""
    return dispatch(
        operation="apply_status_update",
        python_impl=apply_status_update_python,
        args=(lines, changespec_name, new_status),
    )


def transition_changespec_status(
    project_file: str,
    changespec_name: str,
    new_status: str,
    validate: bool = True,
    console: "Console | None" = None,
) -> tuple[bool, str | None, str | None, list[SiblingRevertResult]]:
    """Transition a ChangeSpec STATUS via the active backend."""
    return dispatch(
        operation="transition_changespec_status",
        python_impl=transition_changespec_status_python,
        args=(project_file, changespec_name, new_status),
        kwargs={"validate": validate, "console": console},
        source_path=project_file,
    )
