"""Flag task-bead field validation and drop-flag mirror migration."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from sase.bead import db as db_mod
from sase.bead.flag_fields import FlagFields
from sase.bead.model import Issue, IssueType, Status


def _fields(**overrides: object) -> FlagFields:
    values: dict[str, object] = {
        "key": "demo_key",
        "kind": "beta",
        "remove_by_date": "2026-12-01",
        "remove_by_release": "0.19.0",
    }
    values.update(overrides)
    return FlagFields(**values)  # type: ignore[arg-type]


class TestFlagFieldsValidation:
    def test_valid_record_passes(self) -> None:
        _fields().validate()

    @pytest.mark.parametrize(
        "key", ["", " ", "Demo", "demo-key", "_demo", "demo_", "1demo"]
    )
    def test_key_must_be_non_empty_snake_case(self, key: str) -> None:
        with pytest.raises(ValueError, match="key must be non-empty snake_case"):
            _fields(key=key).validate()

    @pytest.mark.parametrize(
        "value", ["", "2026-12-01T00:00:00Z", "2026/12/01", "soon"]
    )
    def test_remove_by_date_must_be_an_iso_date(self, value: str) -> None:
        with pytest.raises(ValueError, match="remove_by_date must be an ISO date"):
            _fields(remove_by_date=value).validate()

    @pytest.mark.parametrize("value", ["", "v0.19.0", "0.19", "latest"])
    def test_remove_by_release_must_be_a_release_string(self, value: str) -> None:
        with pytest.raises(
            ValueError, match="remove_by_release must be a release string"
        ):
            _fields(remove_by_release=value).validate()

    def test_a_prerelease_suffix_is_accepted(self) -> None:
        _fields(key="plugins_enabled", remove_by_release="0.19.0-rc.1").validate()


def test_fresh_mirror_rejects_the_retired_flag_issue_type(tmp_path: Path) -> None:
    conn = db_mod.init_db(tmp_path / "beads.db")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO issues "
                "(id, title, status, issue_type, created_at, updated_at) "
                "VALUES ('sase-f1', 'Old flag', 'open', 'flag', 'now', 'now')"
            )
    finally:
        conn.close()


def test_flag_task_bead_round_trips_through_the_mirror(tmp_path: Path) -> None:
    issue = Issue(
        id="sase-f1",
        title="Retire demo_key",
        issue_type=IssueType.TASK,
        status=Status.OPEN,
        created_at="2026-08-06T09:00:00Z",
        updated_at="2026-08-06T09:00:00Z",
        task_type="flag",
        task_type_fields={
            "key": "demo_key",
            "kind": "beta",
            "when_enabled": "on",
            "when_disabled": "off",
            "remove_when": "done",
            "remove_by_date": "2026-12-01",
            "remove_by_release": "0.19.0",
        },
    )
    conn = db_mod.init_db(tmp_path / "beads.db")
    try:
        db_mod.create_issue(conn, issue)
        reloaded = db_mod.get_issue(conn, "sase-f1")
    finally:
        conn.close()

    assert reloaded is not None
    assert reloaded.issue_type is IssueType.TASK
    assert reloaded.task_type == "flag"
    assert reloaded.task_type_fields["key"] == "demo_key"
