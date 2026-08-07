"""Storage-layer tests for archived bead close records.

Nothing here renders close history; these tests pin the model, the wire
codec, ``issues.jsonl``, and the compatibility SQLite mirror.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from sase.bead import db as bead_db
from sase.bead.close_history_codec import (
    close_history_from_dicts,
    close_history_to_dicts,
)
from sase.bead._db_schema import SCHEMA_SQL
from sase.bead.db import create_issue, get_issue, init_db
from sase.bead.jsonl import export_to_jsonl, import_from_jsonl
from sase.bead.model import (
    CloseRecord,
    Issue,
    IssueType,
    PhaseSize,
    ReopenCause,
    Resolution,
    Status,
)
from sase.core.bead_wire import issue_from_dict

NOW = "2026-08-05T00:00:00Z"

_CLOSE_HISTORY_COLUMN_DEFINITION = "    close_history TEXT NOT NULL DEFAULT '[]',\n"


def _record(
    *,
    closed_at: str = "2026-07-30T09:12:04Z",
    close_reason: str | None = "Not reproducible on main.",
    resolution: Resolution | None = Resolution.CANCELED,
    reopened_at: str = "2026-08-05T17:04:11Z",
    reopened_via: ReopenCause = ReopenCause.PLUS_ONE,
    reopened_by: str | None = "claude.probe",
) -> CloseRecord:
    return CloseRecord(
        closed_at=closed_at,
        close_reason=close_reason,
        resolution=resolution,
        reopened_at=reopened_at,
        reopened_via=reopened_via,
        reopened_by=reopened_by,
    )


def _task(**kwargs: object) -> Issue:
    fields: dict[str, object] = {
        "id": "t-1",
        "title": "Flaky retry test",
        "issue_type": IssueType.TASK,
        "status": Status.READY,
        "size": PhaseSize.SMALL,
        "created_at": NOW,
        "updated_at": NOW,
    }
    fields.update(kwargs)
    return Issue(**fields)  # type: ignore[arg-type]


class TestModelValidation:
    def test_a_valid_record_passes(self) -> None:
        _task(close_history=[_record()]).validate()

    def test_close_history_is_allowed_on_every_issue_type(self) -> None:
        Issue(
            id="p-1",
            title="Plan",
            issue_type=IssueType.PLAN,
            created_at=NOW,
            updated_at=NOW,
            close_history=[_record(reopened_via=ReopenCause.OPEN, reopened_by=None)],
        ).validate()

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"closed_at": "  "}, "closed_at cannot be empty"),
            ({"reopened_at": ""}, "reopened_at cannot be empty"),
            ({"reopened_by": " "}, "reopened_by cannot be empty"),
        ],
    )
    def test_blank_required_fields_are_rejected(
        self, kwargs: dict[str, str], message: str
    ) -> None:
        issue = _task(close_history=[_record(**kwargs)])  # type: ignore[arg-type]
        with pytest.raises(ValueError, match=message):
            issue.validate()

    def test_absent_optional_fields_are_accepted(self) -> None:
        _task(
            close_history=[
                _record(close_reason=None, resolution=None, reopened_by=None)
            ]
        ).validate()


class TestWireCodec:
    def test_optional_fields_are_omitted_when_absent(self) -> None:
        encoded = close_history_to_dicts(
            [_record(close_reason=None, resolution=None, reopened_by=None)]
        )
        assert encoded == [
            {
                "closed_at": "2026-07-30T09:12:04Z",
                "reopened_at": "2026-08-05T17:04:11Z",
                "reopened_via": "plus_one",
            }
        ]

    def test_full_record_round_trips(self) -> None:
        history = [_record(), _record(reopened_via=ReopenCause.EPIC_PRECLAIM)]
        assert close_history_from_dicts(close_history_to_dicts(history)) == history

    @pytest.mark.parametrize("value", [None, "not-a-list", 7, {}])
    def test_non_list_input_decodes_to_empty(self, value: object) -> None:
        assert close_history_from_dicts(value) == []

    def test_records_with_an_unknown_cause_are_dropped(self) -> None:
        decoded = close_history_from_dicts(
            [
                {
                    "closed_at": NOW,
                    "reopened_at": NOW,
                    "reopened_via": "teleported",
                },
                close_history_to_dicts([_record()])[0],
            ]
        )
        assert [record.reopened_via for record in decoded] == [ReopenCause.PLUS_ONE]

    def test_rust_outcome_dicts_decode_close_history(self) -> None:
        issue = issue_from_dict(
            {
                "id": "t-1",
                "title": "Flaky retry test",
                "status": "ready",
                "issue_type": "task",
                "close_history": close_history_to_dicts([_record()]),
            }
        )
        assert issue.close_history == [_record()]

    def test_rust_outcome_dicts_tolerate_a_missing_key(self) -> None:
        issue = issue_from_dict(
            {"id": "t-1", "title": "T", "status": "open", "issue_type": "task"}
        )
        assert issue.close_history == []


@pytest.fixture
def conn(tmp_path: Path):
    connection = init_db(tmp_path / "beads.db")
    yield connection
    connection.close()


class TestJsonlPersistence:
    def test_round_trip_preserves_every_field(
        self, conn: sqlite3.Connection, tmp_path: Path
    ) -> None:
        create_issue(conn, _task(close_history=[_record()]))
        path = tmp_path / "issues.jsonl"
        export_to_jsonl(conn, path)

        imported = import_from_jsonl(path, init_db(tmp_path / "other.db"))
        assert imported[0].close_history == [_record()]

    def test_the_key_is_omitted_for_beads_that_were_never_reopened(
        self, conn: sqlite3.Connection, tmp_path: Path
    ) -> None:
        create_issue(conn, _task())
        path = tmp_path / "issues.jsonl"
        export_to_jsonl(conn, path)
        assert "close_history" not in json.loads(path.read_text(encoding="utf-8"))

    def test_the_key_sits_between_resolution_and_description(
        self, conn: sqlite3.Connection, tmp_path: Path
    ) -> None:
        create_issue(
            conn,
            _task(
                status=Status.CLOSED,
                closed_at=NOW,
                resolution=Resolution.DONE,
                close_history=[_record()],
            ),
        )
        path = tmp_path / "issues.jsonl"
        export_to_jsonl(conn, path)
        keys = list(json.loads(path.read_text(encoding="utf-8")))
        assert keys.index("resolution") + 1 == keys.index("close_history")
        assert keys.index("close_history") + 1 == keys.index("description")

    def test_a_legacy_row_without_the_key_imports(
        self, conn: sqlite3.Connection, tmp_path: Path
    ) -> None:
        create_issue(conn, _task(close_history=[_record()]))
        path = tmp_path / "issues.jsonl"
        export_to_jsonl(conn, path)
        row = json.loads(path.read_text(encoding="utf-8"))
        row.pop("close_history")
        path.write_text(json.dumps(row) + "\n", encoding="utf-8")

        imported = import_from_jsonl(path, init_db(tmp_path / "legacy.db"))
        assert imported[0].close_history == []

    def test_import_updates_close_history_on_an_existing_row(
        self, conn: sqlite3.Connection, tmp_path: Path
    ) -> None:
        create_issue(conn, _task())
        path = tmp_path / "issues.jsonl"
        row = {
            **json.loads(_exported_row(conn, tmp_path / "seed.jsonl")),
            "close_history": close_history_to_dicts([_record()]),
        }
        path.write_text(json.dumps(row) + "\n", encoding="utf-8")

        import_from_jsonl(path, conn)
        stored = get_issue(conn, "t-1")
        assert stored is not None
        assert stored.close_history == [_record()]


def _exported_row(conn: sqlite3.Connection, path: Path) -> str:
    export_to_jsonl(conn, path)
    return path.read_text(encoding="utf-8").strip()


class TestSqliteMirror:
    def test_stored_and_read_back(self, conn: sqlite3.Connection) -> None:
        create_issue(conn, _task(close_history=[_record(), _record(closed_at=NOW)]))
        stored = get_issue(conn, "t-1")
        assert stored is not None
        assert [record.closed_at for record in stored.close_history] == [
            "2026-07-30T09:12:04Z",
            NOW,
        ]

    def test_a_pre_column_database_migrates_to_an_empty_history(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "old.db"
        old = sqlite3.connect(str(db_path))
        schema_without_column = SCHEMA_SQL.replace(_CLOSE_HISTORY_COLUMN_DEFINITION, "")
        assert schema_without_column != SCHEMA_SQL
        old.executescript(schema_without_column)
        old.execute(
            "INSERT INTO issues "
            "(id, title, status, issue_type, created_at, updated_at) "
            "VALUES ('t-old', 'Old task', 'open', 'task', ?, ?)",
            (NOW, NOW),
        )
        old.commit()
        old.close()

        conn = init_db(db_path)
        try:
            issue = get_issue(conn, "t-old")
            assert issue is not None
            assert issue.close_history == []
        finally:
            conn.close()

    def test_a_corrupt_column_value_reads_as_an_empty_history(
        self, conn: sqlite3.Connection
    ) -> None:
        create_issue(conn, _task(close_history=[_record()]))
        conn.execute("UPDATE issues SET close_history = 'not json' WHERE id = 't-1'")
        stored = get_issue(conn, "t-1")
        assert stored is not None
        assert stored.close_history == []

    def test_the_column_json_matches_the_wire_encoding(
        self, conn: sqlite3.Connection
    ) -> None:
        create_issue(conn, _task(close_history=[_record()]))
        row = conn.execute(
            "SELECT close_history FROM issues WHERE id = 't-1'"
        ).fetchone()
        assert json.loads(row[0]) == close_history_to_dicts([_record()])

    def test_the_encoder_is_reachable_as_a_public_helper(self) -> None:
        assert json.loads(bead_db.close_history_json([_record()])) == (
            close_history_to_dicts([_record()])
        )
