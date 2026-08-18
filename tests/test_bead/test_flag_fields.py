"""The single flag-bead accessor every read path must go through."""

from __future__ import annotations

from sase.bead.flag_fields import (
    FlagFields,
    flag_fields,
    is_flag_bead,
    is_flag_task_bead,
    replace_flag_thresholds,
)
from sase.bead.model import FlagRecord, Issue, IssueType, Status


def _flag_task(**overrides: object) -> Issue:
    fields = {
        "key": "demo_key",
        "kind": "beta",
        "when_enabled": "new path",
        "when_disabled": "old path",
        "remove_when": "when proven",
        "remove_by_date": "2026-12-01",
        "remove_by_release": "0.19.0",
    }
    raw_fields = overrides.pop("task_type_fields", fields)
    return Issue(
        id="sase-xy",
        title="Retire demo_key",
        status=Status.OPEN,
        issue_type=IssueType.TASK,
        task_type="flag",
        task_type_fields=dict(raw_fields) if isinstance(raw_fields, dict) else {},
        **overrides,  # type: ignore[arg-type]
    )


def test_flag_fields_reads_task_type_fields() -> None:
    assert flag_fields(_flag_task()) == FlagFields(
        key="demo_key",
        kind="beta",
        remove_by_date="2026-12-01",
        remove_by_release="0.19.0",
    )
    assert is_flag_task_bead(_flag_task())
    assert is_flag_bead(_flag_task())


def test_flag_fields_reads_legacy_flag_record() -> None:
    issue = Issue(
        id="sase-nw",
        title="Retire demo_key",
        issue_type=IssueType.FLAG,
        flag=FlagRecord(
            key="demo_key",
            remove_by_date="2026-12-01",
            remove_by_release="0.19.0",
        ),
    )

    assert flag_fields(issue) == FlagFields(
        key="demo_key",
        kind="",
        remove_by_date="2026-12-01",
        remove_by_release="0.19.0",
    )
    assert not is_flag_task_bead(issue)
    assert is_flag_bead(issue)


def test_flag_fields_returns_none_for_other_task_types() -> None:
    issue = Issue(
        id="sase-ab",
        title="Flaky",
        issue_type=IssueType.TASK,
        task_type="flake",
        task_type_fields={"node_id": "tests/foo.py::test_bar"},
    )

    assert flag_fields(issue) is None
    assert not is_flag_bead(issue)


def test_flag_fields_returns_none_when_thresholds_are_missing() -> None:
    issue = _flag_task(
        task_type_fields={"key": "demo_key", "kind": "beta"},
    )

    assert flag_fields(issue) is None


def test_replace_flag_thresholds_preserves_other_fields() -> None:
    updated = replace_flag_thresholds(
        {
            "key": "demo_key",
            "kind": "beta",
            "remove_by_date": "2026-12-01",
            "remove_by_release": "0.19.0",
        },
        remove_by_date="2026-12-15",
        remove_by_release="0.20.0",
    )

    assert updated == {
        "key": "demo_key",
        "kind": "beta",
        "remove_by_date": "2026-12-15",
        "remove_by_release": "0.20.0",
    }
