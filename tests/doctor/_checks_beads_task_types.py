"""Tests for doctor task type checks."""

from __future__ import annotations

from sase.doctor import checks_beads
from sase.task_types import TaskTypeDiagnostic, TaskTypeRegistry


def test_check_task_types_ok_when_catalog_is_clean(monkeypatch) -> None:
    import sase.task_types as task_types_pkg

    monkeypatch.setattr(
        task_types_pkg,
        "get_task_type_registry",
        lambda: TaskTypeRegistry(records=(), diagnostics=()),
    )
    result = checks_beads._check_task_types()
    assert result.status == "OK"
    assert result.data["error_count"] == 0
    assert result.data["warning_count"] == 0


def test_check_task_types_reports_errors_and_warnings(monkeypatch) -> None:
    import sase.task_types as task_types_pkg

    registry = TaskTypeRegistry(
        records=(),
        diagnostics=(
            TaskTypeDiagnostic(
                code="duplicate_task_type", message="dup", severity="error"
            ),
            TaskTypeDiagnostic(
                code="duplicate_task_type_color", message="color", severity="warning"
            ),
        ),
    )
    monkeypatch.setattr(task_types_pkg, "get_task_type_registry", lambda: registry)
    result = checks_beads._check_task_types()
    assert result.status == "ERROR"
    assert result.data["error_count"] == 1
    assert result.data["warning_count"] == 1
    assert result.next_steps
