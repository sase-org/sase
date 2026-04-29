"""sase.core facade for status transitions and pure status field helpers.

Wraps :mod:`sase.status_state_machine` behind
:func:`sase.core.backend.dispatch`. Two flavors live here:

- ``read_status_from_lines`` and ``apply_status_update`` are pure functions
  over raw project-file lines. Phase 4D ships them as Rust-backed operations:
  when ``sase_core_rs`` is importable the facade registers the binding as
  ``rust_impl`` and ``SASE_CORE_BACKEND=rust`` routes through it. When the
  extension exposes the binding ``SASE_CORE_DUAL_RUN=1`` runs both impls and
  logs a comparison record. With no extension installed and the default
  Python backend the facade keeps the existing pure-Python path; Rust mode
  without the binding raises :class:`RustBackendUnavailableError`.
- ``transition_changespec_status`` performs disk IO (it acquires a lock and
  rewrites the project file). Phase 4D keeps it on the Python implementation
  with an explicit ``rust_unavailable="python"`` fallback; the Rust planner
  integration is the Phase 4E target.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.core.backend import dispatch, load_rust_extension
from sase.status_state_machine.field_updates import (
    apply_status_update_python,
    read_status_from_lines_python,
)
from sase.status_state_machine.siblings import SiblingRevertResult
from sase.status_state_machine.transitions import transition_changespec_status_python

if TYPE_CHECKING:
    from rich.console import Console


def _rust_read_status_from_lines_impl(
    lines: list[str], changespec_name: str
) -> str | None:
    """Adapter from ``sase_core_rs.read_status_from_lines`` to a Python ``str | None``.

    The PyO3 binding accepts the same positional arguments as the Python
    helper and returns a plain string or ``None``; the adapter exists so a
    later import-time disappearance of the extension surfaces with a clear
    traceback instead of an :class:`AttributeError`.
    """
    rust_module = load_rust_extension()
    if rust_module is None:
        raise RuntimeError(
            "sase_core_rs is not importable; the Rust backend was registered "
            "but the extension module disappeared at call time."
        )
    return rust_module.read_status_from_lines(lines, changespec_name)  # type: ignore[attr-defined,no-any-return]


def _rust_apply_status_update_impl(
    lines: list[str], changespec_name: str, new_status: str
) -> str:
    """Adapter from ``sase_core_rs.apply_status_update`` to a Python ``str``."""
    rust_module = load_rust_extension()
    if rust_module is None:
        raise RuntimeError(
            "sase_core_rs is not importable; the Rust backend was registered "
            "but the extension module disappeared at call time."
        )
    return rust_module.apply_status_update(  # type: ignore[attr-defined,no-any-return]
        lines, changespec_name, new_status
    )


def read_status_from_lines(lines: list[str], changespec_name: str) -> str | None:
    """Read the STATUS field from raw project-file lines via the active backend."""
    rust_module = load_rust_extension()
    rust_impl = (
        _rust_read_status_from_lines_impl
        if rust_module is not None and hasattr(rust_module, "read_status_from_lines")
        else None
    )
    return dispatch(
        operation="read_status_from_lines",
        python_impl=read_status_from_lines_python,
        rust_impl=rust_impl,
        args=(lines, changespec_name),
    )


def apply_status_update(lines: list[str], changespec_name: str, new_status: str) -> str:
    """Return updated file content with the STATUS line rewritten."""
    rust_module = load_rust_extension()
    rust_impl = (
        _rust_apply_status_update_impl
        if rust_module is not None and hasattr(rust_module, "apply_status_update")
        else None
    )
    return dispatch(
        operation="apply_status_update",
        python_impl=apply_status_update_python,
        rust_impl=rust_impl,
        args=(lines, changespec_name, new_status),
    )


def transition_changespec_status(
    project_file: str,
    changespec_name: str,
    new_status: str,
    validate: bool = True,
    console: Console | None = None,
) -> tuple[bool, str | None, str | None, list[SiblingRevertResult]]:
    """Transition a ChangeSpec STATUS via the active backend."""
    return dispatch(
        operation="transition_changespec_status",
        python_impl=transition_changespec_status_python,
        rust_unavailable="python",
        args=(project_file, changespec_name, new_status),
        kwargs={"validate": validate, "console": console},
        source_path=project_file,
    )
