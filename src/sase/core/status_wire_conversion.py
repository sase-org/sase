"""Converters between Python project data and status wire records.

Belongs to the Phase 4B status wire contract (see
:mod:`sase.core.status_wire`). Lives next to the wire module so the
boundary between host-side I/O (parse the project file, walk all
projects, look up parent/children) and the pure decision rules stays
explicit.

Two responsibilities live here:

- :func:`build_status_transition_request` — gather the in-project parent
  status, in-universe children/siblings, and the cross-project
  existing-names set required by
  :class:`~sase.core.status_wire.StatusTransitionRequestWire`. This
  helper performs Python-only filesystem I/O via
  :mod:`sase.ace.changespec` and :mod:`sase.ace.revert`.
- :func:`plan_status_transition_python` — pure decision engine. Given a
  request wire, returns a :class:`~sase.core.status_wire.StatusTransitionPlanWire`
  describing the side effects the host should perform. This is the
  Python implementation that the Rust planner will mirror.

The pure planner uses the same constants as
:mod:`sase.status_state_machine.constants` and reproduces the
validation/error messages emitted by
:mod:`sase.status_state_machine.handlers` so the wire-routed and direct
paths return identical strings.
"""

from __future__ import annotations

from sase.core.changespec import (
    get_next_suffix_number,
    has_suffix,
    strip_reverted_suffix,
)
from sase.core.status_wire import (
    ARCHIVE_ACTION_FROM_ARCHIVE,
    ARCHIVE_ACTION_NONE,
    ARCHIVE_ACTION_TO_ARCHIVE,
    MENTOR_ACTION_CLEAR,
    MENTOR_ACTION_NONE,
    MENTOR_ACTION_SET,
    STATUS_WIRE_SCHEMA_VERSION,
    SUFFIX_ACTION_APPEND,
    SUFFIX_ACTION_NONE,
    SUFFIX_ACTION_STRIP,
    ChangespecChildWire,
    StatusTransitionPlanWire,
    StatusTransitionRequestWire,
)
from sase.status_state_machine.constants import (
    ARCHIVE_STATUSES,
    VALID_TRANSITIONS,
    is_valid_transition,
    remove_workspace_suffix,
)


def _format_invalid_transition_error(
    changespec_name: str, old_status: str, new_status: str
) -> str:
    """Reproduce the rejection string used by the Python handlers."""
    return (
        f"Invalid status transition for '{changespec_name}': "
        f"'{old_status}' -> '{new_status}'. "
        f"Allowed transitions from '{old_status}': "
        f"{VALID_TRANSITIONS.get(old_status, [])}"
    )


def _classify_archive_action(old_status: str | None, new_status: str) -> str:
    """Reproduce the archive-class compare from ``transition_changespec_status_python``.

    The original code does ``old_status in ARCHIVE_STATUSES`` on the raw
    value returned from the file (which can carry a workspace suffix).
    We preserve that literal behaviour for parity; workspace-suffixed
    archive statuses are unusual in practice and changing the
    classification rule belongs to a follow-up.
    """
    old_is_archive = old_status in ARCHIVE_STATUSES if old_status else False
    new_is_archive = new_status in ARCHIVE_STATUSES
    if new_is_archive == old_is_archive:
        return ARCHIVE_ACTION_NONE
    return ARCHIVE_ACTION_TO_ARCHIVE if new_is_archive else ARCHIVE_ACTION_FROM_ARCHIVE


def _failure_plan(
    request: StatusTransitionRequestWire, error: str
) -> StatusTransitionPlanWire:
    return StatusTransitionPlanWire(
        schema_version=STATUS_WIRE_SCHEMA_VERSION,
        success=False,
        old_status=request.old_status,
        error=error,
    )


def plan_status_transition_python(
    request: StatusTransitionRequestWire,
) -> StatusTransitionPlanWire:
    """Pure Python implementation of the status transition planner.

    The function never performs I/O. All required context is on the
    :class:`StatusTransitionRequestWire`.

    The decision tree mirrors
    :func:`sase.status_state_machine.transitions.transition_changespec_status_python`
    branch-for-branch:

    - WIP→Draft: validate only.
    - Ready→Draft: blocking-children check, validate, suffix append,
      mentor draft set.
    - new_status=Ready (from any old_status): parent constraint,
      validate, sibling-unreverted-children check (when suffixed and
      old in WIP/Draft), suffix strip, mentor clear (Draft→Ready only).
    - new_status=Reverted / Archived: validate only.
    - else (Mailed/Submitted/...): treated like the generic ready
      handler — parent constraint plus validate; no suffix/mentor work.

    On failure the plan carries ``success=False``, the unchanged
    ``old_status``, and the rejection ``error`` string. On success it
    carries the action fields the host should execute (see
    :class:`StatusTransitionPlanWire`).
    """
    if request.schema_version != STATUS_WIRE_SCHEMA_VERSION:
        raise ValueError(
            f"status wire schema mismatch: got {request.schema_version}, "
            f"expected {STATUS_WIRE_SCHEMA_VERSION}"
        )

    changespec_name = request.changespec_name
    old_status = request.old_status
    new_status = request.new_status
    validate = request.validate

    base_old_status = remove_workspace_suffix(old_status)

    # Branch: Ready -> Draft (suffix append + mentor set)
    if new_status == "Draft" and base_old_status == "Ready":
        if request.blocking_children:
            child_info = ", ".join(
                f"{c.name} ({c.status})" for c in request.blocking_children
            )
            return _failure_plan(
                request,
                (
                    f"Cannot transition '{changespec_name}' to Draft: "
                    f"children must be WIP, Draft, or Reverted. "
                    f"Invalid children: {child_info}"
                ),
            )
        if validate and not is_valid_transition(old_status, new_status):
            return _failure_plan(
                request,
                _format_invalid_transition_error(
                    changespec_name, old_status, new_status
                ),
            )

        suffix_num = get_next_suffix_number(
            changespec_name, set(request.existing_names)
        )
        suffixed_name = f"{changespec_name}_{suffix_num}"
        return StatusTransitionPlanWire(
            schema_version=STATUS_WIRE_SCHEMA_VERSION,
            success=True,
            old_status=old_status,
            error=None,
            status_update_target=new_status,
            suffix_action=SUFFIX_ACTION_APPEND,
            suffixed_name=suffixed_name,
            base_name=changespec_name,
            mentor_draft_action=MENTOR_ACTION_SET,
            archive_action=_classify_archive_action(old_status, new_status),
            timestamp_event=f"{old_status} -> {new_status}",
            timestamp_target_name=suffixed_name,
        )

    # Branch: WIP -> Draft (no suffix, no mentor)
    if new_status == "Draft" and base_old_status == "WIP":
        if validate and not is_valid_transition(old_status, new_status):
            return _failure_plan(
                request,
                _format_invalid_transition_error(
                    changespec_name, old_status, new_status
                ),
            )
        return StatusTransitionPlanWire(
            schema_version=STATUS_WIRE_SCHEMA_VERSION,
            success=True,
            old_status=old_status,
            error=None,
            status_update_target=new_status,
            archive_action=_classify_archive_action(old_status, new_status),
            timestamp_event=f"{old_status} -> {new_status}",
            timestamp_target_name=changespec_name,
        )

    # Branch: Reverted (terminal) — validate only
    if new_status == "Reverted":
        if validate and not is_valid_transition(old_status, new_status):
            return _failure_plan(
                request,
                _format_invalid_transition_error(
                    changespec_name, old_status, new_status
                ),
            )
        return StatusTransitionPlanWire(
            schema_version=STATUS_WIRE_SCHEMA_VERSION,
            success=True,
            old_status=old_status,
            error=None,
            status_update_target=new_status,
            archive_action=_classify_archive_action(old_status, new_status),
            timestamp_event=f"{old_status} -> {new_status}",
            timestamp_target_name=changespec_name,
        )

    # Branch: Archived (terminal) — validate only
    if new_status == "Archived":
        if validate and not is_valid_transition(old_status, new_status):
            return _failure_plan(
                request,
                _format_invalid_transition_error(
                    changespec_name, old_status, new_status
                ),
            )
        return StatusTransitionPlanWire(
            schema_version=STATUS_WIRE_SCHEMA_VERSION,
            success=True,
            old_status=old_status,
            error=None,
            status_update_target=new_status,
            archive_action=_classify_archive_action(old_status, new_status),
            timestamp_event=f"{old_status} -> {new_status}",
            timestamp_target_name=changespec_name,
        )

    # Generic "ready" branch: covers new_status=Ready, Mailed, Submitted, ...
    # 1) Parent constraint: if in-project parent is WIP/Draft, the child can
    #    only become WIP/Draft/Reverted.
    if request.parent_status in ("WIP", "Draft") and new_status not in (
        "WIP",
        "Draft",
        "Reverted",
    ):
        return _failure_plan(
            request,
            (
                f"Cannot transition '{changespec_name}' to {new_status}: "
                f"parent is {request.parent_status}. "
                f"Children of WIP/Draft ChangeSpecs must be WIP, Draft, or Reverted."
            ),
        )

    # 2) Validate the transition itself.
    if validate and not is_valid_transition(old_status, new_status):
        return _failure_plan(
            request,
            _format_invalid_transition_error(changespec_name, old_status, new_status),
        )

    # 3) Sibling-unreverted-children check on WIP/Draft -> Ready with suffix.
    if (
        new_status == "Ready"
        and base_old_status in ("WIP", "Draft")
        and has_suffix(changespec_name)
        and request.siblings_with_unreverted_children
    ):
        # First-hit sibling NAME — the planner doesn't carry sibling
        # statuses on the wire, so the rejection string omits the parens.
        sibling = request.siblings_with_unreverted_children[0]
        return _failure_plan(
            request,
            (
                f"Cannot transition '{changespec_name}' to Ready: "
                f"sibling ChangeSpec '{sibling}' has unreverted children."
            ),
        )

    # Suffix strip on WIP/Draft -> Ready with suffix.
    suffix_action = SUFFIX_ACTION_NONE
    strip_suffixed_name: str | None = None
    strip_base_name: str | None = None
    mentor_draft_action = MENTOR_ACTION_NONE
    revert_siblings = False
    if (
        new_status == "Ready"
        and base_old_status in ("WIP", "Draft")
        and has_suffix(changespec_name)
    ):
        suffix_action = SUFFIX_ACTION_STRIP
        strip_suffixed_name = changespec_name
        strip_base_name = strip_reverted_suffix(changespec_name)
        revert_siblings = True

    # Mentor flag clear on Draft -> Ready (independent of suffix).
    if base_old_status == "Draft" and new_status == "Ready":
        mentor_draft_action = MENTOR_ACTION_CLEAR

    # Post-rename name for the timestamp event.
    timestamp_target_name = (
        strip_base_name if suffix_action == SUFFIX_ACTION_STRIP else changespec_name
    )

    return StatusTransitionPlanWire(
        schema_version=STATUS_WIRE_SCHEMA_VERSION,
        success=True,
        old_status=old_status,
        error=None,
        status_update_target=new_status,
        suffix_action=suffix_action,
        suffixed_name=strip_suffixed_name,
        base_name=strip_base_name,
        mentor_draft_action=mentor_draft_action,
        archive_action=_classify_archive_action(old_status, new_status),
        timestamp_event=f"{old_status} -> {new_status}",
        timestamp_target_name=timestamp_target_name,
        revert_siblings=revert_siblings,
    )


def build_status_transition_request(
    project_file: str,
    changespec_name: str,
    old_status: str,
    new_status: str,
    validate: bool = True,
) -> StatusTransitionRequestWire:
    """Build a :class:`StatusTransitionRequestWire` from on-disk state.

    Performs the Python-only I/O the planner needs:

    - parses the in-project ``ChangeSpec`` list to look up the parent's
      base status;
    - walks ``find_all_changespecs()`` (across projects) when the
      transition is Ready→Draft, both for blocking-children and to seed
      ``existing_names``;
    - builds ``siblings_with_unreverted_children`` for the
      WIP/Draft→Ready + suffix path.

    The ``old_status`` argument is the value the host has already read
    under lock via :func:`read_status_from_lines`. Passing it in
    explicitly keeps the request hermetic (the planner doesn't have to
    re-read the file) and matches the existing handler signatures.

    Args:
        project_file: Path to the project ``.gp`` file.
        changespec_name: NAME of the ChangeSpec being transitioned.
        old_status: STATUS as read from the file (workspace suffix
            tolerated).
        new_status: Target STATUS.
        validate: Whether the planner should enforce
            :func:`is_valid_transition`.

    Returns:
        A fully populated request wire.
    """
    from sase.ace.changespec import find_all_changespecs, parse_project_file
    from sase.ace.revert import has_children

    base_old_status = remove_workspace_suffix(old_status)
    parent_status: str | None = None
    blocking_children: tuple[ChangespecChildWire, ...] = ()
    siblings_with_unreverted_children: tuple[str, ...] = ()
    existing_names: tuple[str, ...] = ()

    project_changespecs = parse_project_file(project_file)
    current_cs = next(
        (cs for cs in project_changespecs if cs.name == changespec_name), None
    )

    # Parent status lookup — only meaningful for the "ready"-style branch.
    if current_cs is not None and current_cs.parent:
        parent_cs = next(
            (cs for cs in project_changespecs if cs.name == current_cs.parent),
            None,
        )
        if parent_cs is not None:
            parent_status = remove_workspace_suffix(parent_cs.status)

    # Cross-project context for Ready -> Draft.
    if new_status == "Draft" and base_old_status == "Ready":
        all_changespecs = find_all_changespecs()
        existing_names = tuple(cs.name for cs in all_changespecs)
        invalid_children = [
            cs
            for cs in all_changespecs
            if cs.parent == changespec_name
            and cs.status not in ("WIP", "Draft", "Reverted")
        ]
        blocking_children = tuple(
            ChangespecChildWire(name=cs.name, status=remove_workspace_suffix(cs.status))
            for cs in invalid_children
        )

    # Sibling unreverted-children check for WIP/Draft -> Ready with suffix.
    if (
        new_status == "Ready"
        and base_old_status in ("WIP", "Draft")
        and has_suffix(changespec_name)
    ):
        all_changespecs = find_all_changespecs()
        base_name = strip_reverted_suffix(changespec_name)
        offenders: list[str] = []
        for cs in project_changespecs:
            if cs.name == changespec_name:
                continue
            cs_base = strip_reverted_suffix(cs.name)
            if cs_base == base_name and cs.status in ("WIP", "Draft"):
                if has_children(cs, all_changespecs):
                    offenders.append(cs.name)
        siblings_with_unreverted_children = tuple(offenders)

    return StatusTransitionRequestWire(
        schema_version=STATUS_WIRE_SCHEMA_VERSION,
        changespec_name=changespec_name,
        old_status=old_status,
        new_status=new_status,
        validate=validate,
        parent_status=parent_status,
        blocking_children=blocking_children,
        siblings_with_unreverted_children=siblings_with_unreverted_children,
        existing_names=existing_names,
    )


__all__ = [
    "build_status_transition_request",
    "plan_status_transition_python",
]
