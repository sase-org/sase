"""Unit tests for off-thread init-plan unified diffs."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.modals.projects_pane_init_diffs import (
    MAX_DIFF_LINES,
    attach_action_diffs,
)
from sase.ace.tui.modals.projects_pane_init_payload import InitCheckPayload

from .projects_pane_init_test_helpers import (
    action_row,
    check_payload,
    planner_row,
    project_plan,
)


def _payload_with_action(**kwargs: object) -> InitCheckPayload:
    action = action_row(**kwargs)  # type: ignore[arg-type]
    return check_payload(
        project_plan(
            "sase",
            status="needs_attention",
            planners=(
                planner_row(
                    "memory",
                    has_changes=True,
                    summary="1 update",
                    actions=(action,),
                ),
            ),
        )
    )


def test_create_against_missing_file_is_all_added(tmp_path: Path) -> None:
    missing = tmp_path / "new.md"
    payload = _payload_with_action(
        path=str(missing),
        operation="create",
        new_content="one\ntwo\n",
    )

    result = attach_action_diffs(payload)
    action = result.projects[0].planners[0].actions[0]

    assert action.diff_note is None
    assert action.added == 2
    assert action.removed == 0
    assert any(line.startswith("+one") for line in action.diff_lines)


def test_update_against_real_file_counts_added_and_removed(tmp_path: Path) -> None:
    path = tmp_path / "existing.md"
    path.write_text("old\nkeep\n", encoding="utf-8")
    payload = _payload_with_action(
        path=str(path),
        operation="update",
        new_content="new\nkeep\n",
    )

    result = attach_action_diffs(payload)
    action = result.projects[0].planners[0].actions[0]

    assert action.diff_note is None
    assert action.added == 1
    assert action.removed == 1
    assert any(line.startswith("-old") for line in action.diff_lines)
    assert any(line.startswith("+new") for line in action.diff_lines)


def test_base64_action_is_binary_content_with_no_diff() -> None:
    payload = _payload_with_action(
        operation="create",
        new_content="AAAA",
        new_content_encoding="base64",
    )

    result = attach_action_diffs(payload)
    action = result.projects[0].planners[0].actions[0]

    assert action.diff_note == "binary content"
    assert action.diff_lines == ()
    assert action.added == 0
    assert action.removed == 0


def test_missing_new_content_is_validate_note() -> None:
    payload = _payload_with_action(
        operation="validate",
        new_content=None,
    )

    result = attach_action_diffs(payload)
    action = result.projects[0].planners[0].actions[0]

    assert action.diff_note == "no file content in this plan"
    assert action.diff_lines == ()


def test_relative_path_is_diff_unavailable_and_does_not_raise() -> None:
    payload = _payload_with_action(
        path="relative/file.md",
        operation="update",
        new_content="hello\n",
    )

    result = attach_action_diffs(payload)
    action = result.projects[0].planners[0].actions[0]

    assert action.diff_note == "diff unavailable"


def test_unreadable_existing_file_is_diff_unavailable(tmp_path: Path) -> None:
    path = tmp_path / "binary.bin"
    path.write_bytes(b"\xff\xfe\x00")
    payload = _payload_with_action(
        path=str(path),
        operation="update",
        new_content="hello\n",
    )

    result = attach_action_diffs(payload)
    action = result.projects[0].planners[0].actions[0]

    assert action.diff_note == "diff unavailable"


def test_max_diff_lines_appends_explicit_marker(tmp_path: Path) -> None:
    new_content = "".join(f"line-{index}\n" for index in range(MAX_DIFF_LINES + 20))
    payload = _payload_with_action(
        path=str(tmp_path / "missing.md"),
        operation="create",
        new_content=new_content,
    )

    result = attach_action_diffs(payload)
    action = result.projects[0].planners[0].actions[0]

    assert action.diff_lines[-1].startswith("… ")
    assert "more diff lines" in action.diff_lines[-1]
    assert len(action.diff_lines) == MAX_DIFF_LINES + 1
    assert action.added == MAX_DIFF_LINES + 20
