"""sase.core facade for status transitions and pure status field helpers.

Wraps :mod:`sase.status_state_machine` behind
:func:`sase.core.backend.dispatch`. Three flavors live here:

- ``read_status_from_lines`` and ``apply_status_update`` are pure functions
  over raw project-file lines. Phase 4D ships them as Rust-backed operations:
  when ``sase_core_rs`` is importable the facade registers the binding as
  ``rust_impl`` and ``SASE_CORE_BACKEND=rust`` routes through it. When the
  extension exposes the binding ``SASE_CORE_DUAL_RUN=1`` runs both impls and
  logs a comparison record. With no extension installed and the default
  Python backend the facade keeps the existing pure-Python path; Rust mode
  without the binding raises :class:`RustBackendUnavailableError`.
- ``plan_status_transition`` is the pure decision engine introduced in
  Phase 4E. The Python implementation lives in
  :mod:`sase.core.status_wire_conversion`. When ``sase_core_rs`` exposes
  ``plan_status_transition``, the facade registers it as ``rust_impl`` so
  ``SASE_CORE_BACKEND=rust`` evaluates the transition decision in Rust and
  ``SASE_CORE_DUAL_RUN=1`` compares the two plan dicts. The dispatcher
  always returns the Python-typed :class:`StatusTransitionPlanWire` so
  callers (notably :func:`transition_changespec_status_python`) never see
  the cross-language dict layer.
- ``transition_changespec_status`` performs disk IO (it acquires a lock and
  rewrites the project file). Phase 4E keeps it on the Python implementation
  with an explicit ``rust_unavailable="python"`` fallback because dual-run on
  this entry point would duplicate every side effect; the Rust planner
  integration happens *inside* :func:`transition_changespec_status_python`
  via the ``plan_status_transition`` facade above.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.core.backend import dispatch, load_rust_extension
from sase.core.status_wire import (
    StatusTransitionPlanWire,
    StatusTransitionRequestWire,
    status_plan_from_dict,
    status_wire_to_json_dict,
)
from sase.core.status_wire_conversion import plan_status_transition_python
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


def _rust_plan_status_transition_impl(
    request: StatusTransitionRequestWire,
) -> StatusTransitionPlanWire:
    """Adapter from ``sase_core_rs.plan_status_transition`` to a typed plan.

    The PyO3 binding accepts a request-shape dict and returns a plan-shape
    dict; this rebuilds :class:`StatusTransitionPlanWire` via
    :func:`status_plan_from_dict` so callers see the same Python record
    regardless of backend.
    """
    rust_module = load_rust_extension()
    if rust_module is None:
        raise RuntimeError(
            "sase_core_rs is not importable; the Rust backend was registered "
            "but the extension module disappeared at call time."
        )
    payload: dict[str, Any] = rust_module.plan_status_transition(  # type: ignore[attr-defined]
        status_wire_to_json_dict(request),
    )
    return status_plan_from_dict(payload)


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


def plan_status_transition(
    request: StatusTransitionRequestWire,
) -> StatusTransitionPlanWire:
    """Plan a status transition for one ChangeSpec via the active backend.

    The request is the pre-gathered host context (parent status, blocking
    children, sibling info, existing-name set) — see
    :class:`StatusTransitionRequestWire` for the contract. The returned
    plan describes the side effects the host should execute; this function
    performs none of them.

    Phase 4E classifies ``plan_status_transition`` as a shipped Rust
    operation: under ``SASE_CORE_BACKEND=rust`` the binding is required and
    a missing one raises :class:`RustBackendUnavailableError`. With the
    default Python backend the pure decision engine in
    :mod:`sase.core.status_wire_conversion` is used, and
    ``SASE_CORE_DUAL_RUN=1`` runs both implementations and logs a
    comparison record.
    """
    rust_module = load_rust_extension()
    rust_impl = (
        _rust_plan_status_transition_impl
        if rust_module is not None and hasattr(rust_module, "plan_status_transition")
        else None
    )
    return dispatch(
        operation="plan_status_transition",
        python_impl=plan_status_transition_python,
        rust_impl=rust_impl,
        args=(request,),
    )


def transition_changespec_status(
    project_file: str,
    changespec_name: str,
    new_status: str,
    validate: bool = True,
    console: Console | None = None,
) -> tuple[bool, str | None, str | None, list[SiblingRevertResult]]:
    """Transition a ChangeSpec STATUS via the active backend.

    Phase 4E keeps this entry point on Python with
    ``rust_unavailable="python"``: dual-running the full transition would
    apply every disk-bound side effect (atomic rewrites, archive moves,
    suffix renames, mentor flag updates, VCS calls) twice. The Rust
    planner integration happens inside
    :func:`transition_changespec_status_python` via the
    ``plan_status_transition`` facade entry above, so the pure decision
    step still routes through Rust under ``SASE_CORE_BACKEND=rust`` while
    Python remains responsible for every side effect.
    """
    return dispatch(
        operation="transition_changespec_status",
        python_impl=transition_changespec_status_python,
        rust_unavailable="python",
        args=(project_file, changespec_name, new_status),
        kwargs={"validate": validate, "console": console},
        source_path=project_file,
    )
