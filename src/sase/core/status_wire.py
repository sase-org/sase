"""Wire records for the ChangeSpec status state machine facade.

Companion to :mod:`sase.core.wire`, :mod:`sase.core.query_wire`, and
:mod:`sase.core.agent_scan_wire`. Defines the **stable** boundary between
Python and a future Rust implementation of the status decision engine
(Phase 4 of ``research/202604/rust_backend_migration.md`` and
``sdd/plans/202604/rust_backend_phase4_status_machine.md``).

Scope of the contract
---------------------

The status wire models *pure decision* inputs and outputs. Host-side side
effects — file locks, atomic writes, archive moves, timestamp recording,
mentor flag mutation, suffix branch renames, parent-reference updates,
``RUNNING`` updates, VCS calls — stay in Python and are NEVER described by
these records.

Two records cross the boundary:

- :class:`StatusTransitionRequestWire` — primitive inputs the host has
  pre-gathered: current/target status, validation flag, and the
  pre-computed flags needed by the decision rules (parent status,
  blocking children, sibling info, existing-name set).
- :class:`StatusTransitionPlanWire` — what the host should do after the
  decision: write a new STATUS line, perform a suffix rename, set/clear
  mentor draft flags, move between main/archive files, record a
  timestamp, auto-revert siblings.

Two helper records support pure line transformations under the
``read_status_from_lines`` / ``apply_status_update`` facades. They live
here so a Rust implementation can share the same Python-side schema:

- :class:`StatusFieldReadWire` — request to read a STATUS field given a
  list of project-file lines and a ChangeSpec name.
- :class:`StatusFieldUpdateWire` — request to apply a STATUS update over
  a list of lines.

Wire records intentionally hold only primitive types (``str``, ``int``,
``bool``, ``None``, and tuples of these). They never carry ``Path``,
``Console``, ``ChangeSpec``, VCS providers, locks, or callables. Frozen
dataclasses are used so a record is hashable and can be safely cached.

JSON shape conventions
----------------------

- All keys are lowercase ``snake_case``.
- ``None`` is preserved (becomes JSON ``null``).
- Tuples serialise as JSON arrays.
- Enumerated string fields (``suffix_action``, ``mentor_draft_action``,
  ``archive_action``) carry the literal value, not an enum index.

Schema version
--------------

:data:`STATUS_WIRE_SCHEMA_VERSION` is bumped whenever the shape changes
incompatibly. The Rust implementation pins the same version constant in
its serde structs; mismatches surface immediately in
:func:`status_request_from_dict` / :func:`status_plan_from_dict`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

STATUS_WIRE_SCHEMA_VERSION = 1


# Suffix actions on a successful transition.
SUFFIX_ACTION_NONE = "none"
SUFFIX_ACTION_STRIP = "strip"
SUFFIX_ACTION_APPEND = "append"

# Mentor draft-flag actions.
MENTOR_ACTION_NONE = "none"
MENTOR_ACTION_SET = "set_draft"
MENTOR_ACTION_CLEAR = "clear_draft"

# File-classification actions (main vs. archive).
ARCHIVE_ACTION_NONE = "none"
ARCHIVE_ACTION_TO_ARCHIVE = "to_archive"
ARCHIVE_ACTION_FROM_ARCHIVE = "from_archive"


@dataclass(frozen=True)
class ChangespecChildWire:
    """A child reference used by the parent/children decision rules.

    Attributes:
        name: ChangeSpec NAME as it appears on disk (may include a
            ``_<N>`` suffix).
        status: Base STATUS for the child. Workspace suffixes
            (``" (<project>_<N>)"``) MUST be stripped by the caller via
            :func:`sase.status_state_machine.constants.remove_workspace_suffix`
            before being placed on the wire — the Rust planner expects
            the canonical status string.
    """

    name: str
    status: str


@dataclass(frozen=True)
class StatusTransitionRequestWire:
    """Pure inputs the host has gathered for one transition decision.

    The host is responsible for:

    - reading the current STATUS line under lock and passing it as
      ``old_status`` (workspace suffixes are passed through verbatim — the
      planner strips them when validating);
    - resolving ``parent_status`` for the in-project parent reference, if
      any;
    - filtering ``blocking_children`` to children of the changespec whose
      base status is **not** in ``{WIP, Draft, Reverted}`` (only those are
      relevant to the Ready→Draft rule);
    - determining ``siblings_with_unreverted_children`` — sibling NAMES
      sharing the changespec's base name that are themselves in
      ``{WIP, Draft}`` and have at least one non-Reverted child somewhere
      in the universe (only used by the WIP/Draft→Ready + suffix rule);
    - collecting ``existing_names`` from across projects so the planner
      can pick a unique ``_<N>`` suffix on Ready→Draft.

    Attributes:
        schema_version: Must equal :data:`STATUS_WIRE_SCHEMA_VERSION`.
        changespec_name: NAME of the ChangeSpec being transitioned.
        old_status: STATUS as read from the project file. May carry a
            workspace suffix (``" (<project>_<N>)"``); the planner
            normalises before validation.
        new_status: Target STATUS value (without workspace suffix).
        validate: When False, the planner skips
            :func:`is_valid_transition`. Mirrors the existing
            ``validate=False`` escape hatch used by archive restore.
        parent_status: STATUS of the changespec named by the in-project
            PARENT field, normalised through
            :func:`remove_workspace_suffix`. ``None`` when there is no
            parent or the parent is missing in this project.
        blocking_children: Children of ``changespec_name`` whose base
            status is not in ``{WIP, Draft, Reverted}``. The planner
            rejects Ready→Draft when this tuple is non-empty.
        siblings_with_unreverted_children: NAMES of WIP/Draft siblings
            sharing the changespec's base name that have unreverted
            children. Triggers a rejection on WIP/Draft→Ready with a
            ``_<N>`` suffix.
        existing_names: Names already in use across all projects. Used
            to pick the lowest free ``_<N>`` slot on Ready→Draft. The
            tuple ordering does not matter; the planner treats it as a
            set.
    """

    schema_version: int
    changespec_name: str
    old_status: str
    new_status: str
    validate: bool
    parent_status: str | None
    blocking_children: tuple[ChangespecChildWire, ...] = ()
    siblings_with_unreverted_children: tuple[str, ...] = ()
    existing_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class StatusTransitionPlanWire:
    """The decision the planner reached, ready for the host to execute.

    A plan with ``success=False`` carries a non-``None`` ``error`` and
    leaves the action fields at their no-op defaults. A plan with
    ``success=True`` describes everything the host has to do *after* the
    STATUS line is rewritten.

    Side-effect ordering, reproduced from
    :func:`transition_changespec_status_python`:

    1. Write ``status_update_target`` to the STATUS line via
       :func:`apply_status_update` and atomically persist the file.
    2. If ``mentor_draft_action`` is ``set_draft`` or ``clear_draft``,
       update mentor flags.
    3. (Outside the lock.) If ``suffix_action`` is ``strip``, rename the
       changespec to ``base_name`` and auto-revert siblings; if
       ``append``, rename to ``suffixed_name``.
    4. Move between main and archive files when ``archive_action`` is
       ``to_archive`` or ``from_archive``.
    5. Record a timestamp under ``timestamp_target_name`` with payload
       ``timestamp_event`` if ``timestamp_event`` is set.

    Attributes:
        schema_version: Must equal :data:`STATUS_WIRE_SCHEMA_VERSION`.
        success: True when the transition is allowed. False indicates a
            validation rejection — ``error`` carries the user-visible
            message.
        old_status: Echo of :attr:`StatusTransitionRequestWire.old_status`.
            Returned so the host's tuple-typed return value
            (``(success, old_status, error_msg, sibling_revert_results)``)
            stays well defined even on failure paths.
        error: Human-readable rejection reason. ``None`` on success.
        status_update_target: The exact string to write to the STATUS
            line on success. ``None`` when ``success=False``.
        suffix_action: One of :data:`SUFFIX_ACTION_NONE`,
            :data:`SUFFIX_ACTION_STRIP`, or :data:`SUFFIX_ACTION_APPEND`.
        suffixed_name: The ``_<N>``-suffixed NAME. Set when
            ``suffix_action`` is ``strip`` (the *current* suffixed name)
            or ``append`` (the *new* suffixed name).
        base_name: The unsuffixed NAME. Set when ``suffix_action`` is
            ``strip`` (the *new* unsuffixed name) or ``append`` (the
            *current* unsuffixed name).
        mentor_draft_action: One of :data:`MENTOR_ACTION_NONE`,
            :data:`MENTOR_ACTION_SET`, or :data:`MENTOR_ACTION_CLEAR`.
        archive_action: One of :data:`ARCHIVE_ACTION_NONE`,
            :data:`ARCHIVE_ACTION_TO_ARCHIVE`, or
            :data:`ARCHIVE_ACTION_FROM_ARCHIVE`.
        timestamp_event: Payload string for the timestamp record, e.g.
            ``"Ready -> Mailed"``. ``None`` when no timestamp should be
            recorded (``success=False`` or ``old_status=None``).
        timestamp_target_name: NAME under which the timestamp should be
            recorded. Equals the post-rename name when a suffix action
            is performed, otherwise the original ``changespec_name``.
            ``None`` when no timestamp should be recorded.
        revert_siblings: True when the host should auto-revert sibling
            WIP/Draft ChangeSpecs sharing the base name. Only set on the
            WIP/Draft→Ready + suffix path.
    """

    schema_version: int
    success: bool
    old_status: str | None
    error: str | None
    status_update_target: str | None = None
    suffix_action: str = SUFFIX_ACTION_NONE
    suffixed_name: str | None = None
    base_name: str | None = None
    mentor_draft_action: str = MENTOR_ACTION_NONE
    archive_action: str = ARCHIVE_ACTION_NONE
    timestamp_event: str | None = None
    timestamp_target_name: str | None = None
    revert_siblings: bool = False


@dataclass(frozen=True)
class StatusFieldReadWire:
    """Inputs for :func:`read_status_from_lines`.

    Provided as a structured record so the Rust binding can accept the
    same shape (``{"lines": [...], "changespec_name": "..."}``) without
    a custom positional argspec. The Python facade still exposes the
    legacy positional API and converts at the boundary.
    """

    lines: tuple[str, ...]
    changespec_name: str


@dataclass(frozen=True)
class StatusFieldUpdateWire:
    """Inputs for :func:`apply_status_update`.

    See :class:`StatusFieldReadWire` for the rationale.
    """

    lines: tuple[str, ...]
    changespec_name: str
    new_status: str


def status_wire_to_json_dict(record: Any) -> Any:
    """Project a status-wire dataclass to a JSON-safe shape.

    Mirrors :func:`sase.core.agent_scan_wire.agent_scan_wire_to_json_dict`
    but is local to this module so the status wire stays independent of
    other facades' schema bumps.
    """
    if isinstance(record, (list, tuple)):
        return [status_wire_to_json_dict(item) for item in record]
    if isinstance(record, dict):
        return {k: status_wire_to_json_dict(v) for k, v in record.items()}
    if hasattr(record, "__dataclass_fields__"):
        return asdict(record)
    return record


def _children_from_seq(data: Any) -> tuple[ChangespecChildWire, ...]:
    if not data:
        return ()
    out: list[ChangespecChildWire] = []
    for item in data:
        if isinstance(item, ChangespecChildWire):
            out.append(item)
        elif isinstance(item, dict):
            out.append(
                ChangespecChildWire(
                    name=str(item["name"]),
                    status=str(item["status"]),
                )
            )
        else:
            raise TypeError(f"Cannot decode ChangespecChildWire from {type(item)!r}")
    return tuple(out)


def status_request_from_dict(data: dict[str, Any]) -> StatusTransitionRequestWire:
    """Rehydrate a :class:`StatusTransitionRequestWire` from a dict.

    Inverse of :func:`status_wire_to_json_dict` for request records.
    Used by the future PyO3 binding adapter and by tests that round-trip
    a request through JSON. Unknown top-level keys raise ``TypeError``.
    """
    schema = int(data["schema_version"])
    if schema != STATUS_WIRE_SCHEMA_VERSION:
        raise ValueError(
            f"status wire schema mismatch: got {schema}, "
            f"expected {STATUS_WIRE_SCHEMA_VERSION}"
        )
    return StatusTransitionRequestWire(
        schema_version=schema,
        changespec_name=str(data["changespec_name"]),
        old_status=str(data["old_status"]),
        new_status=str(data["new_status"]),
        validate=bool(data["validate"]),
        parent_status=(
            None if data.get("parent_status") is None else str(data["parent_status"])
        ),
        blocking_children=_children_from_seq(data.get("blocking_children")),
        siblings_with_unreverted_children=tuple(
            str(name) for name in data.get("siblings_with_unreverted_children") or ()
        ),
        existing_names=tuple(str(name) for name in data.get("existing_names") or ()),
    )


def status_plan_from_dict(data: dict[str, Any]) -> StatusTransitionPlanWire:
    """Rehydrate a :class:`StatusTransitionPlanWire` from a dict.

    Used by the Rust adapter (the binding returns a plain Python dict)
    and by tests that round-trip a plan through JSON.
    """
    schema = int(data["schema_version"])
    if schema != STATUS_WIRE_SCHEMA_VERSION:
        raise ValueError(
            f"status wire schema mismatch: got {schema}, "
            f"expected {STATUS_WIRE_SCHEMA_VERSION}"
        )
    return StatusTransitionPlanWire(
        schema_version=schema,
        success=bool(data["success"]),
        old_status=(
            None if data.get("old_status") is None else str(data["old_status"])
        ),
        error=None if data.get("error") is None else str(data["error"]),
        status_update_target=(
            None
            if data.get("status_update_target") is None
            else str(data["status_update_target"])
        ),
        suffix_action=str(data.get("suffix_action", SUFFIX_ACTION_NONE)),
        suffixed_name=(
            None if data.get("suffixed_name") is None else str(data["suffixed_name"])
        ),
        base_name=(None if data.get("base_name") is None else str(data["base_name"])),
        mentor_draft_action=str(data.get("mentor_draft_action", MENTOR_ACTION_NONE)),
        archive_action=str(data.get("archive_action", ARCHIVE_ACTION_NONE)),
        timestamp_event=(
            None
            if data.get("timestamp_event") is None
            else str(data["timestamp_event"])
        ),
        timestamp_target_name=(
            None
            if data.get("timestamp_target_name") is None
            else str(data["timestamp_target_name"])
        ),
        revert_siblings=bool(data.get("revert_siblings", False)),
    )


__all__ = [
    "ARCHIVE_ACTION_FROM_ARCHIVE",
    "ARCHIVE_ACTION_NONE",
    "ARCHIVE_ACTION_TO_ARCHIVE",
    "MENTOR_ACTION_CLEAR",
    "MENTOR_ACTION_NONE",
    "MENTOR_ACTION_SET",
    "STATUS_WIRE_SCHEMA_VERSION",
    "SUFFIX_ACTION_APPEND",
    "SUFFIX_ACTION_NONE",
    "SUFFIX_ACTION_STRIP",
    "ChangespecChildWire",
    "StatusFieldReadWire",
    "StatusFieldUpdateWire",
    "StatusTransitionPlanWire",
    "StatusTransitionRequestWire",
    "status_plan_from_dict",
    "status_request_from_dict",
    "status_wire_to_json_dict",
]
