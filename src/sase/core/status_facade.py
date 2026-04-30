"""sase.core facade for status transitions and pure status field helpers.

The three pure status operations (:func:`read_status_from_lines`,
:func:`apply_status_update`, :func:`plan_status_transition`) call
``sase_core_rs`` directly through :func:`sase.core.rust.require_rust_binding`.
:func:`plan_status_transition` marshals the request through
:func:`status_wire_to_json_dict`, calls the Rust planner, and rebuilds the
typed :class:`StatusTransitionPlanWire` so callers never see the
cross-language dict layer.

:func:`transition_changespec_status` performs disk IO (it acquires a lock
and rewrites the project file) and is Python-owned host logic; the Rust
planner integration happens *inside*
:func:`transition_changespec_status_python` via the
:func:`plan_status_transition` facade entry above.

The Python golden helpers
:func:`sase.status_state_machine.field_updates.read_status_from_lines_python`,
:func:`sase.status_state_machine.field_updates.apply_status_update_python`,
and :func:`sase.core.status_wire_conversion.plan_status_transition_python`
remain in their modules as the byte-for-byte golden references for the
parity tests against the Rust implementations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.core.rust import require_rust_binding
from sase.core.status_wire import (
    StatusTransitionPlanWire,
    StatusTransitionRequestWire,
    status_plan_from_dict,
    status_wire_to_json_dict,
)
from sase.status_state_machine.siblings import SiblingRevertResult
from sase.status_state_machine.transitions import transition_changespec_status_python

if TYPE_CHECKING:
    from rich.console import Console


def read_status_from_lines(lines: list[str], changespec_name: str) -> str | None:
    """Read the STATUS field from raw project-file lines via ``sase_core_rs``."""
    binding = require_rust_binding("read_status_from_lines")
    return binding(lines, changespec_name)  # type: ignore[no-any-return]


def apply_status_update(lines: list[str], changespec_name: str, new_status: str) -> str:
    """Return updated file content with the STATUS line rewritten via ``sase_core_rs``."""
    binding = require_rust_binding("apply_status_update")
    return binding(lines, changespec_name, new_status)  # type: ignore[no-any-return]


def plan_status_transition(
    request: StatusTransitionRequestWire,
) -> StatusTransitionPlanWire:
    """Plan a status transition for one ChangeSpec via ``sase_core_rs``.

    The request is the pre-gathered host context (parent status, blocking
    children, sibling info, existing-name set) — see
    :class:`StatusTransitionRequestWire` for the contract. The returned
    plan describes the side effects the host should execute; this function
    performs none of them.
    """
    binding = require_rust_binding("plan_status_transition")
    payload: dict[str, Any] = binding(status_wire_to_json_dict(request))
    return status_plan_from_dict(payload)


def transition_changespec_status(
    project_file: str,
    changespec_name: str,
    new_status: str,
    validate: bool = True,
    console: Console | None = None,
) -> tuple[bool, str | None, str | None, list[SiblingRevertResult]]:
    """Transition a ChangeSpec STATUS.

    This entry point is intentionally Python-owned host logic: it
    acquires a file lock and applies disk-bound side effects (atomic
    rewrites, archive moves, suffix renames, mentor flag updates, VCS
    calls). The Rust planner integration happens *inside*
    :func:`transition_changespec_status_python` via the
    :func:`plan_status_transition` facade entry above, so the pure
    decision step still routes through Rust while Python remains
    responsible for every side effect.
    """
    return transition_changespec_status_python(
        project_file,
        changespec_name,
        new_status,
        validate=validate,
        console=console,
    )
