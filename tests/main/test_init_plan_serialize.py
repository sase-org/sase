"""Tests for the shared init-plan serializer."""

from __future__ import annotations

from pathlib import Path

from sase.doctor.checks_config_common import MAX_DETAIL_ROWS
from sase.main.init_plan import InitAction, InitPlan, serialize_init_plan


def test_serialize_init_plan_matches_doctor_row_without_run_fields() -> None:
    plan = InitPlan(
        command="memory",
        label="Memory",
        summary="1 update",
        actions=(
            InitAction(
                Path("sase/task_types.json"),
                "update",
                "refresh snapshot",
                new_content='{"ok": true}\n',
            ),
        ),
        warnings=("note",),
        blockers=(),
        requires_tty=True,
    )

    row = serialize_init_plan(plan, max_actions=MAX_DETAIL_ROWS)

    assert row == {
        "name": "memory",
        "label": "Memory",
        "summary": "1 update",
        "actions": [
            {
                "path": "sase/task_types.json",
                "operation": "update",
                "detail": "refresh snapshot",
            }
        ],
        "action_count": 1,
        "warnings": ["note"],
        "blockers": [],
    }
    assert "truncated" not in row
    assert "new_content" not in row["actions"][0]
    assert "requires_tty" not in row


def test_serialize_init_plan_marks_truncation_and_keeps_full_count() -> None:
    actions = tuple(
        InitAction(Path(f"file-{index}.md"), "update", f"row {index}")
        for index in range(MAX_DETAIL_ROWS + 3)
    )
    plan = InitPlan(
        command="skills",
        label="Skills",
        summary="many updates",
        actions=actions,
    )

    row = serialize_init_plan(plan, max_actions=MAX_DETAIL_ROWS)

    assert len(row["actions"]) == MAX_DETAIL_ROWS
    assert row["action_count"] == MAX_DETAIL_ROWS + 3
    assert row["truncated"] is True


def test_serialize_init_plan_json_fields_include_content_and_tty() -> None:
    plan = InitPlan(
        command="memory",
        label="Memory",
        summary="1 update",
        actions=(
            InitAction(
                Path("sase/task_types.json"),
                "update",
                "refresh snapshot",
                new_content='{"ok": true}\n',
            ),
            InitAction(
                Path("icon.png"), "overwrite", "binary", new_content=b"\x00\x01"
            ),
        ),
        requires_tty=False,
    )

    row = serialize_init_plan(plan, include_content=True, include_run_fields=True)

    assert row["has_changes"] is True
    assert row["runnable"] is True
    assert row["requires_tty"] is False
    assert row["actions"][0]["new_content"] == '{"ok": true}\n'
    assert row["actions"][0]["content_encoding"] == "utf-8"
    assert row["actions"][1]["content_encoding"] == "base64"
    assert row["actions"][1]["new_content"] == "AAE="
    assert "truncated" not in row
