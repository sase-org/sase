"""Golden tests for the Phase 4B status wire contract.

These tests pin down the shape of
:class:`sase.core.status_wire.StatusTransitionRequestWire` /
:class:`StatusTransitionPlanWire` and the decision behaviour of
:func:`sase.core.status_wire_conversion.plan_status_transition_python`.

The Rust planner added in Phase 4C must reproduce the plans exercised
here, so any edit to a golden plan should be a deliberate parity-breaking
change with a matching Rust update.
"""

from __future__ import annotations

import json

import pytest

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
    StatusFieldReadWire,
    StatusFieldUpdateWire,
    StatusTransitionPlanWire,
    StatusTransitionRequestWire,
    status_plan_from_dict,
    status_request_from_dict,
    status_wire_to_json_dict,
)
from sase.core.status_wire_conversion import (
    build_status_transition_request,
    plan_status_transition_python,
)


def _request(
    *,
    changespec_name: str = "proj_feature",
    old_status: str = "WIP",
    new_status: str = "Draft",
    validate: bool = True,
    parent_status: str | None = None,
    blocking_children: tuple[ChangespecChildWire, ...] = (),
    siblings_with_unreverted_children: tuple[str, ...] = (),
    existing_names: tuple[str, ...] = (),
) -> StatusTransitionRequestWire:
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


# --- Field-helper wire records ------------------------------------------------


def test_status_field_read_wire_constructs() -> None:
    """The line-helper request shape is stable for the Phase 4D PyO3 binding."""
    rec = StatusFieldReadWire(
        lines=("NAME: foo\n", "STATUS: Ready\n"),
        changespec_name="foo",
    )
    assert rec.lines == ("NAME: foo\n", "STATUS: Ready\n")
    assert rec.changespec_name == "foo"


def test_status_field_update_wire_constructs() -> None:
    """``apply_status_update`` request shape pinned for the binding."""
    rec = StatusFieldUpdateWire(
        lines=("NAME: foo\n", "STATUS: Ready\n"),
        changespec_name="foo",
        new_status="Mailed",
    )
    assert rec.new_status == "Mailed"


# --- build_status_transition_request smoke -----------------------------------


def test_build_status_transition_request_reads_parent_status(tmp_path) -> None:
    """The converter resolves the parent's STATUS from the same project file."""
    project = tmp_path / "proj.gp"
    project.write_text(
        "NAME: proj_parent\n"
        "DESCRIPTION:\n"
        "  parent desc\n"
        "STATUS: WIP\n"
        "\n---\n"
        "NAME: proj_child\n"
        "DESCRIPTION:\n"
        "  child desc\n"
        "PARENT: proj_parent\n"
        "STATUS: Ready\n"
        "\n---\n"
    )
    request = build_status_transition_request(
        project_file=str(project),
        changespec_name="proj_child",
        old_status="Ready",
        new_status="Mailed",
    )
    assert request.parent_status == "WIP"
    # No suffix on child name → no sibling check needed.
    assert request.siblings_with_unreverted_children == ()
    # Ready→Mailed isn't the Ready→Draft branch → no existing_names walk.
    assert request.existing_names == ()


# --- Wire shape / round-trip --------------------------------------------------


def test_request_round_trips_through_json() -> None:
    req = _request(
        changespec_name="proj_foo",
        old_status="Ready (proj_2)",
        new_status="Draft",
        blocking_children=(ChangespecChildWire(name="proj_foo_child", status="Ready"),),
        existing_names=("proj_foo", "proj_foo_1"),
    )
    payload = status_wire_to_json_dict(req)
    decoded = json.loads(json.dumps(payload))
    rebuilt = status_request_from_dict(decoded)
    assert rebuilt == req


def test_plan_round_trips_through_json() -> None:
    plan = StatusTransitionPlanWire(
        schema_version=STATUS_WIRE_SCHEMA_VERSION,
        success=True,
        old_status="Ready",
        error=None,
        status_update_target="Draft",
        suffix_action=SUFFIX_ACTION_APPEND,
        suffixed_name="proj_foo_3",
        base_name="proj_foo",
        mentor_draft_action=MENTOR_ACTION_SET,
        archive_action=ARCHIVE_ACTION_NONE,
        timestamp_event="Ready -> Draft",
        timestamp_target_name="proj_foo_3",
    )
    payload = status_wire_to_json_dict(plan)
    rebuilt = status_plan_from_dict(json.loads(json.dumps(payload)))
    assert rebuilt == plan


def test_schema_version_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="schema mismatch"):
        status_request_from_dict(
            {
                "schema_version": STATUS_WIRE_SCHEMA_VERSION + 99,
                "changespec_name": "x",
                "old_status": "WIP",
                "new_status": "Draft",
                "validate": True,
                "parent_status": None,
            }
        )
    with pytest.raises(ValueError, match="schema mismatch"):
        status_plan_from_dict(
            {
                "schema_version": STATUS_WIRE_SCHEMA_VERSION + 99,
                "success": True,
                "old_status": "WIP",
                "error": None,
            }
        )


# --- Validation: invalid transitions ------------------------------------------


def test_invalid_transition_validate_true_rejects() -> None:
    plan = plan_status_transition_python(
        _request(old_status="Ready", new_status="Submitted")
    )
    assert plan.success is False
    assert plan.error is not None
    assert "Invalid status transition" in plan.error
    assert "'Ready' -> 'Submitted'" in plan.error
    assert plan.old_status == "Ready"
    assert plan.status_update_target is None


def test_invalid_transition_validate_false_allows() -> None:
    """validate=False mirrors the archive-restore escape hatch."""
    plan = plan_status_transition_python(
        _request(old_status="Ready", new_status="Submitted", validate=False)
    )
    assert plan.success is True
    assert plan.status_update_target == "Submitted"


def test_unknown_status_rejected_under_validation() -> None:
    plan = plan_status_transition_python(
        _request(old_status="Bogus", new_status="Mailed")
    )
    assert plan.success is False


# --- Workspace suffix stripping ----------------------------------------------


def test_workspace_suffix_does_not_block_validation() -> None:
    """``Ready (proj_2)`` should normalise to ``Ready`` before validating."""
    plan = plan_status_transition_python(
        _request(
            changespec_name="proj_thing",
            old_status="Ready (proj_2)",
            new_status="Mailed",
        )
    )
    assert plan.success is True
    assert plan.status_update_target == "Mailed"
    # The plan echoes the raw old_status (as the host returns it).
    assert plan.old_status == "Ready (proj_2)"
    # Timestamp event uses the raw old_status string.
    assert plan.timestamp_event == "Ready (proj_2) -> Mailed"


def test_legacy_ready_to_mail_suffix_stripped() -> None:
    plan = plan_status_transition_python(
        _request(
            changespec_name="proj_thing",
            old_status="Ready - (!: READY TO MAIL)",
            new_status="Mailed",
        )
    )
    assert plan.success is True
    assert plan.status_update_target == "Mailed"


# --- WIP -> Draft simple branch -----------------------------------------------


def test_wip_to_draft_no_suffix_no_mentor() -> None:
    plan = plan_status_transition_python(
        _request(
            changespec_name="proj_feature",
            old_status="WIP",
            new_status="Draft",
        )
    )
    assert plan.success is True
    assert plan.status_update_target == "Draft"
    assert plan.suffix_action == SUFFIX_ACTION_NONE
    assert plan.mentor_draft_action == MENTOR_ACTION_NONE
    assert plan.archive_action == ARCHIVE_ACTION_NONE
    assert plan.timestamp_event == "WIP -> Draft"
    assert plan.timestamp_target_name == "proj_feature"


# --- Ready -> Draft (suffix append) -------------------------------------------


def test_ready_to_draft_appends_suffix_and_sets_mentor_draft() -> None:
    plan = plan_status_transition_python(
        _request(
            changespec_name="proj_feature",
            old_status="Ready",
            new_status="Draft",
            existing_names=("proj_feature",),
        )
    )
    assert plan.success is True
    assert plan.suffix_action == SUFFIX_ACTION_APPEND
    assert plan.suffixed_name == "proj_feature_1"
    assert plan.base_name == "proj_feature"
    assert plan.mentor_draft_action == MENTOR_ACTION_SET
    assert plan.timestamp_event == "Ready -> Draft"
    # Timestamp is recorded under the post-rename name.
    assert plan.timestamp_target_name == "proj_feature_1"


def test_ready_to_draft_picks_lowest_free_suffix() -> None:
    plan = plan_status_transition_python(
        _request(
            changespec_name="proj_feature",
            old_status="Ready",
            new_status="Draft",
            existing_names=(
                "proj_feature",
                "proj_feature_1",
                "proj_feature_2",
                "proj_feature__3",  # legacy double-underscore reserved
            ),
        )
    )
    assert plan.success is True
    assert plan.suffixed_name == "proj_feature_4"


def test_ready_to_draft_blocked_by_invalid_children() -> None:
    plan = plan_status_transition_python(
        _request(
            changespec_name="proj_feature",
            old_status="Ready",
            new_status="Draft",
            blocking_children=(
                ChangespecChildWire(name="proj_child_a", status="Mailed"),
                ChangespecChildWire(name="proj_child_b", status="Submitted"),
            ),
        )
    )
    assert plan.success is False
    assert plan.error is not None
    assert "children must be WIP, Draft, or Reverted" in plan.error
    assert "proj_child_a (Mailed)" in plan.error
    assert "proj_child_b (Submitted)" in plan.error


# --- WIP/Draft -> Ready (suffix strip + sibling auto-revert) -----------------


def test_wip_to_ready_with_suffix_strips_and_reverts_siblings() -> None:
    plan = plan_status_transition_python(
        _request(
            changespec_name="proj_feature_2",
            old_status="WIP",
            new_status="Ready",
        )
    )
    assert plan.success is True
    assert plan.suffix_action == SUFFIX_ACTION_STRIP
    assert plan.suffixed_name == "proj_feature_2"
    assert plan.base_name == "proj_feature"
    assert plan.revert_siblings is True
    # WIP -> Ready must not touch mentor draft flags (WIP has no mentors).
    assert plan.mentor_draft_action == MENTOR_ACTION_NONE
    assert plan.timestamp_target_name == "proj_feature"


def test_draft_to_ready_with_suffix_strips_and_clears_mentors() -> None:
    plan = plan_status_transition_python(
        _request(
            changespec_name="proj_feature_3",
            old_status="Draft",
            new_status="Ready",
        )
    )
    assert plan.success is True
    assert plan.suffix_action == SUFFIX_ACTION_STRIP
    assert plan.base_name == "proj_feature"
    assert plan.mentor_draft_action == MENTOR_ACTION_CLEAR
    assert plan.revert_siblings is True


def test_draft_to_ready_no_suffix_no_strip_clears_mentors() -> None:
    plan = plan_status_transition_python(
        _request(
            changespec_name="proj_feature",
            old_status="Draft",
            new_status="Ready",
        )
    )
    assert plan.success is True
    assert plan.suffix_action == SUFFIX_ACTION_NONE
    assert plan.mentor_draft_action == MENTOR_ACTION_CLEAR
    assert plan.revert_siblings is False


def test_wip_to_ready_blocked_by_sibling_unreverted_children() -> None:
    plan = plan_status_transition_python(
        _request(
            changespec_name="proj_feature_2",
            old_status="WIP",
            new_status="Ready",
            siblings_with_unreverted_children=("proj_feature_1",),
        )
    )
    assert plan.success is False
    assert plan.error is not None
    assert "sibling ChangeSpec 'proj_feature_1'" in plan.error
    assert "unreverted children" in plan.error


# --- Parent constraint --------------------------------------------------------


def test_parent_wip_blocks_child_to_mailed() -> None:
    plan = plan_status_transition_python(
        _request(
            changespec_name="proj_child",
            old_status="Ready",
            new_status="Mailed",
            parent_status="WIP",
        )
    )
    assert plan.success is False
    assert plan.error is not None
    assert "parent is WIP" in plan.error
    assert "WIP, Draft, or Reverted" in plan.error


def test_parent_constraint_skipped_for_reverted_branch() -> None:
    """The Reverted target uses its own handler — parent constraint doesn't apply.

    The parent constraint only fires in the generic "ready"-style branch, so
    a Reverted target is only blocked by the transition validator itself.
    """
    plan = plan_status_transition_python(
        _request(
            changespec_name="proj_child",
            old_status="Ready",
            new_status="Reverted",
            parent_status="WIP",
            validate=False,
        )
    )
    assert plan.success is True
    assert plan.status_update_target == "Reverted"


def test_parent_ready_does_not_block_mailed() -> None:
    plan = plan_status_transition_python(
        _request(
            changespec_name="proj_child",
            old_status="Ready",
            new_status="Mailed",
            parent_status="Ready",
        )
    )
    assert plan.success is True


# --- Terminal statuses -------------------------------------------------------


def test_reverted_terminal_no_further_transitions() -> None:
    plan = plan_status_transition_python(
        _request(old_status="Reverted", new_status="WIP")
    )
    assert plan.success is False
    assert plan.error is not None
    assert "Invalid status transition" in plan.error


def test_archived_terminal_no_further_transitions() -> None:
    plan = plan_status_transition_python(
        _request(old_status="Archived", new_status="WIP")
    )
    assert plan.success is False


def test_submitted_terminal_no_further_transitions() -> None:
    plan = plan_status_transition_python(
        _request(old_status="Submitted", new_status="Mailed")
    )
    assert plan.success is False


# --- Archive action classification -------------------------------------------


def test_archive_action_to_archive_on_submitted() -> None:
    plan = plan_status_transition_python(
        _request(old_status="Mailed", new_status="Submitted")
    )
    assert plan.success is True
    assert plan.archive_action == ARCHIVE_ACTION_TO_ARCHIVE


def test_archive_action_from_archive_under_no_validate() -> None:
    plan = plan_status_transition_python(
        _request(old_status="Submitted", new_status="Ready", validate=False)
    )
    assert plan.success is True
    assert plan.archive_action == ARCHIVE_ACTION_FROM_ARCHIVE


def test_archive_action_none_within_main_class() -> None:
    """WIP and Draft both live in the main file — no movement required."""
    plan = plan_status_transition_python(_request(old_status="WIP", new_status="Draft"))
    assert plan.success is True
    assert plan.archive_action == ARCHIVE_ACTION_NONE


def test_archive_action_none_within_archive_class() -> None:
    """Submitted -> Archived stays in the archive file (validate skipped)."""
    plan = plan_status_transition_python(
        _request(old_status="Submitted", new_status="Archived", validate=False)
    )
    assert plan.success is True
    assert plan.archive_action == ARCHIVE_ACTION_NONE
