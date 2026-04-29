"""Main status transition logic for ChangeSpecs.

The Python entry point separates three concerns explicitly so the pure
decision step can route through Rust under ``SASE_CORE_BACKEND=rust``
while every side effect remains on the host:

1. **Input gathering under lock** — read the project file, read the
   current STATUS line, and build the
   :class:`~sase.core.status_wire.StatusTransitionRequestWire` via
   :func:`sase.core.status_wire_conversion.build_status_transition_request`
   (which performs the cross-project reads the planner needs).
2. **Pure decision** — call
   :func:`sase.core.status_facade.plan_status_transition`. The facade
   dispatches to the Rust planner when the optional ``sase_core_rs``
   extension is loaded and the rust backend is selected; otherwise it
   uses :func:`sase.core.status_wire_conversion.plan_status_transition_python`.
3. **Side-effect execution** — apply the returned plan: rewrite the
   STATUS line atomically, mutate mentor flags, perform suffix renames,
   move between main/archive files, and record the transition timestamp.

The lock surrounds steps 1, 2, and the in-lock side effects of step 3
(the STATUS line rewrite and mentor flag mutation). Steps that touch
multiple files or VCS state — suffix renames, archive moves, and
timestamp recording — run after the lock releases, mirroring the
pre-Phase 4E behavior.
"""

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from sase.ace.changespec import changespec_lock
from sase.core.status_wire import (
    ARCHIVE_ACTION_FROM_ARCHIVE,
    ARCHIVE_ACTION_NONE,
    ARCHIVE_ACTION_TO_ARCHIVE,
    MENTOR_ACTION_CLEAR,
    MENTOR_ACTION_NONE,
    MENTOR_ACTION_SET,
    SUFFIX_ACTION_APPEND,
    SUFFIX_ACTION_NONE,
    SUFFIX_ACTION_STRIP,
)
from .field_updates import apply_status_update, read_status_from_lines
from .siblings import SiblingRevertResult
from .suffix import handle_suffix_append, handle_suffix_strip

if TYPE_CHECKING:
    from rich.console import Console

logger = logging.getLogger(__name__)


def transition_changespec_status(
    project_file: str,
    changespec_name: str,
    new_status: str,
    validate: bool = True,
    console: "Console | None" = None,
) -> tuple[bool, str | None, str | None, list[SiblingRevertResult]]:
    """Transition a ChangeSpec to a new STATUS.

    Public entry point — routes through :mod:`sase.core.status`. The default
    backend dispatches back to :func:`transition_changespec_status_python`
    below.
    """
    from sase.core.status_facade import transition_changespec_status as _facade

    return _facade(project_file, changespec_name, new_status, validate, console)


def transition_changespec_status_python(
    project_file: str,
    changespec_name: str,
    new_status: str,
    validate: bool = True,
    console: "Console | None" = None,
) -> tuple[bool, str | None, str | None, list[SiblingRevertResult]]:
    """Python implementation of :func:`transition_changespec_status`.

    Acquires a lock for the read-validate-write cycle, then runs the
    out-of-lock side effects (suffix renames, archive moves, timestamp).
    The pure decision is delegated to
    :func:`sase.core.status_facade.plan_status_transition`, which routes
    to Rust when ``SASE_CORE_BACKEND=rust`` and the binding is installed.

    Args:
        project_file: Path to the ProjectSpec file.
        changespec_name: NAME of the ChangeSpec to update.
        new_status: New STATUS value.
        validate: If True, validate the transition is allowed.
        console: Optional Rich console for output during sibling reverts.

    Returns:
        Tuple of (success, old_status, error_msg, sibling_revert_results).
    """
    from sase.core.status_facade import plan_status_transition
    from sase.core.status_wire_conversion import build_status_transition_request

    sibling_results: list[SiblingRevertResult] = []

    with changespec_lock(project_file):
        with open(project_file, encoding="utf-8") as f:
            lines = f.readlines()

        old_status = read_status_from_lines(lines, changespec_name)
        if old_status is None:
            error_msg = f"ChangeSpec '{changespec_name}' not found in {project_file}"
            logger.error(error_msg)
            return (False, None, error_msg, sibling_results)

        # Stage 1: gather inputs.
        request = build_status_transition_request(
            project_file=project_file,
            changespec_name=changespec_name,
            old_status=old_status,
            new_status=new_status,
            validate=validate,
        )

        # Stage 2: pure decision (Rust-routable).
        plan = plan_status_transition(request)

        if not plan.success:
            logger.error(plan.error)
            return (False, plan.old_status, plan.error, sibling_results)

        # Stage 3: in-lock side effects (STATUS line rewrite + mentor flags).
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_msg = (
            f"[{timestamp}] Transitioning {changespec_name}: "
            f"'{old_status}' -> '{new_status}'"
        )
        if not validate:
            log_msg += " (validation skipped)"
        logger.info(log_msg)

        from sase.ace.changespec import write_changespec_atomic

        assert plan.status_update_target is not None
        updated_content = apply_status_update(
            lines, changespec_name, plan.status_update_target
        )
        write_changespec_atomic(
            project_file,
            updated_content,
            f"Update STATUS to {plan.status_update_target} for {changespec_name}",
        )

        if plan.mentor_draft_action == MENTOR_ACTION_SET:
            from sase.ace.mentors import set_mentor_draft_flags

            set_mentor_draft_flags(project_file, changespec_name)
        elif plan.mentor_draft_action == MENTOR_ACTION_CLEAR:
            from sase.ace.mentors import clear_mentor_draft_flags

            clear_mentor_draft_flags(project_file, changespec_name)
        elif plan.mentor_draft_action != MENTOR_ACTION_NONE:
            raise ValueError(
                f"unexpected mentor_draft_action: {plan.mentor_draft_action!r}"
            )

    # Stage 4: post-lock side effects.

    # 4a: suffix rename (handles parent references, RUNNING field, branch
    # rename, and sibling reverts).
    if plan.suffix_action == SUFFIX_ACTION_STRIP:
        assert plan.suffixed_name is not None and plan.base_name is not None
        sibling_results = handle_suffix_strip(
            project_file, plan.suffixed_name, plan.base_name, console
        )
    elif plan.suffix_action == SUFFIX_ACTION_APPEND:
        assert plan.base_name is not None and plan.suffixed_name is not None
        handle_suffix_append(project_file, plan.base_name, plan.suffixed_name)
    elif plan.suffix_action != SUFFIX_ACTION_NONE:
        raise ValueError(f"unexpected suffix_action: {plan.suffix_action!r}")

    # 4b: archive move (between main and archive .gp files).
    if plan.archive_action != ARCHIVE_ACTION_NONE:
        from sase.ace.changespec.archive import (
            get_archive_file_path,
            get_main_file_path,
            is_archive_file,
            move_changespec_to_file,
        )

        if is_archive_file(project_file):
            main_file = get_main_file_path(project_file)
            archive_file = project_file
        else:
            main_file = project_file
            archive_file = get_archive_file_path(project_file)

        if plan.archive_action == ARCHIVE_ACTION_TO_ARCHIVE:
            move_changespec_to_file(main_file, archive_file, changespec_name)
        elif plan.archive_action == ARCHIVE_ACTION_FROM_ARCHIVE:
            move_changespec_to_file(archive_file, main_file, changespec_name)
        else:
            raise ValueError(f"unexpected archive_action: {plan.archive_action!r}")

    # 4c: STATUS timestamp.
    if plan.timestamp_event is not None and plan.timestamp_target_name is not None:
        from sase.ace.timestamps.recording import add_timestamp_entry_atomic

        add_timestamp_entry_atomic(
            project_file,
            plan.timestamp_target_name,
            "STATUS",
            plan.timestamp_event,
        )

    return (True, plan.old_status, None, sibling_results)
