"""Tests for the snoozed task-bead status across the Python surfaces.

The Rust core owns the snooze mutations; these tests cover the Python
mirror of the model and the three storage surfaces that have to agree about
what a snooze record means: the Rust wire dicts, ``issues.jsonl``, and the
compatibility SQLite mirror.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from sase.bead import db as db_mod
from sase.bead.jsonl import export_to_jsonl, import_from_jsonl
from sase.bead.model import Issue, IssueType, PhaseSize, SnoozeRecord, Status
from sase.bead.snooze_codec import snooze_from_dict, snooze_to_dict
from sase.core.bead_wire import issue_from_dict

UNTIL = "2026-08-09T09:00:00-04:00"
SNOOZED_AT = "2026-08-06T09:00:00Z"


def snooze_record(**overrides: object) -> SnoozeRecord:
    fields: dict[str, object] = {
        "until": UNTIL,
        "snoozed_at": SNOOZED_AT,
        "snoozed_by": "bryanbugyi34@gmail.com",
        "plus_one_target": 3,
        "plus_one_baseline": 1,
        "reason": "waiting on upstream",
    }
    fields.update(overrides)
    return SnoozeRecord(**fields)  # type: ignore[arg-type]


def snoozed_task(**overrides: object) -> Issue:
    fields: dict[str, object] = {
        "id": "sase-a1",
        "title": "A deferred task",
        "issue_type": IssueType.TASK,
        "status": Status.SNOOZED,
        "created_at": SNOOZED_AT,
        "updated_at": SNOOZED_AT,
        "size": PhaseSize.SMALL,
        "snooze": snooze_record(),
    }
    fields.update(overrides)
    return Issue(**fields)  # type: ignore[arg-type]


class TestSnoozeRecordValidation:
    def test_valid_record_passes_and_reports_remaining_plus_ones(self) -> None:
        issue = snoozed_task()
        issue.validate()

        assert issue.snooze is not None
        assert issue.snooze.plus_ones_remaining == 2

    def test_no_target_means_no_remaining_count(self) -> None:
        record = snooze_record(plus_one_target=None, plus_one_baseline=None)

        assert record.plus_ones_remaining is None

    @pytest.mark.parametrize("until", ["2026-08-09T09:00:00", "soon", ""])
    def test_wake_time_requires_an_offset(self, until: str) -> None:
        issue = snoozed_task(snooze=snooze_record(until=until))

        with pytest.raises(ValueError, match="until must be an RFC-3339"):
            issue.validate()

    @pytest.mark.parametrize("field", ["snoozed_at", "snoozed_by"])
    def test_attribution_fields_cannot_be_blank(self, field: str) -> None:
        issue = snoozed_task(snooze=snooze_record(**{field: "  "}))

        with pytest.raises(ValueError, match=f"{field} cannot be empty"):
            issue.validate()

    def test_plus_one_target_must_exceed_the_baseline(self) -> None:
        issue = snoozed_task(
            snooze=snooze_record(plus_one_target=1, plus_one_baseline=1)
        )

        with pytest.raises(ValueError, match="must exceed plus_one_baseline"):
            issue.validate()


class TestSnoozedStatusValidation:
    def test_only_task_beads_can_be_snoozed(self) -> None:
        issue = snoozed_task(issue_type=IssueType.PHASE, parent_id="sase-a")

        with pytest.raises(ValueError, match="Only task issues can have snoozed"):
            issue.validate()

    def test_snoozed_status_requires_the_record(self) -> None:
        issue = snoozed_task(snooze=None)

        with pytest.raises(ValueError, match="must carry snooze metadata"):
            issue.validate()

    def test_the_record_requires_snoozed_status(self) -> None:
        issue = snoozed_task(status=Status.READY)

        with pytest.raises(ValueError, match="Only snoozed issues can carry"):
            issue.validate()


class TestSnoozeCodec:
    def test_wire_dict_round_trips_in_core_field_order(self) -> None:
        encoded = snooze_to_dict(snooze_record())

        assert list(encoded) == [
            "until",
            "snoozed_at",
            "snoozed_by",
            "plus_one_target",
            "plus_one_baseline",
            "reason",
        ]
        assert snooze_from_dict(encoded) == snooze_record()

    def test_absent_plus_one_keys_are_omitted_not_nulled(self) -> None:
        encoded = snooze_to_dict(
            snooze_record(plus_one_target=None, plus_one_baseline=None)
        )

        assert "plus_one_target" not in encoded
        assert "plus_one_baseline" not in encoded

    @pytest.mark.parametrize("value", [None, "", [], 3])
    def test_unusable_payloads_decode_to_none(self, value: object) -> None:
        assert snooze_from_dict(value) is None

    def test_junk_plus_one_values_degrade_instead_of_raising(self) -> None:
        record = snooze_from_dict(
            {
                "until": UNTIL,
                "snoozed_at": SNOOZED_AT,
                "snoozed_by": "me",
                "plus_one_target": "three",
                "reason": None,
            }
        )

        assert record is not None
        assert record.plus_one_target is None
        assert record.reason == ""


class TestSnoozeReadFacadeWire:
    def test_issue_from_dict_decodes_the_record(self) -> None:
        issue = issue_from_dict(
            {
                "id": "sase-a1",
                "title": "A deferred task",
                "status": "snoozed",
                "issue_type": "task",
                "snooze": snooze_to_dict(snooze_record()),
            }
        )

        assert issue.status is Status.SNOOZED
        assert issue.snooze == snooze_record()

    def test_a_row_without_a_snooze_key_decodes_to_none(self) -> None:
        issue = issue_from_dict(
            {"id": "sase-a1", "title": "T", "status": "ready", "issue_type": "task"}
        )

        assert issue.snooze is None


class TestSnoozeJsonlProjection:
    def test_row_round_trips_and_omits_the_key_when_absent(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "issues.jsonl"
        snoozed = snoozed_task()
        plain = Issue(
            id="sase-a2",
            title="An ordinary task",
            issue_type=IssueType.TASK,
            status=Status.READY,
            created_at=SNOOZED_AT,
            updated_at=SNOOZED_AT,
        )

        source = db_mod.init_db(tmp_path / "source.db")
        try:
            db_mod.create_issue(source, snoozed)
            db_mod.create_issue(source, plain)
            export_to_jsonl(source, path)
        finally:
            source.close()

        rows = {
            json.loads(line)["id"]: json.loads(line)
            for line in path.read_text().splitlines()
        }

        assert rows["sase-a1"]["snooze"] == snooze_to_dict(snooze_record())
        assert "snooze" not in rows["sase-a2"]

        conn = db_mod.init_db(tmp_path / "beads.db")
        try:
            import_from_jsonl(path, conn)
            reloaded = db_mod.get_issue(conn, "sase-a1")
        finally:
            conn.close()

        assert reloaded is not None
        assert reloaded.status is Status.SNOOZED
        assert reloaded.snooze == snooze_record()


class TestSnoozeSqliteMirror:
    def test_a_snoozed_row_survives_a_write_and_read(self, tmp_path: Path) -> None:
        conn = db_mod.init_db(tmp_path / "beads.db")
        try:
            db_mod.create_issue(conn, snoozed_task())
            reloaded = db_mod.get_issue(conn, "sase-a1")
        finally:
            conn.close()

        assert reloaded is not None
        assert reloaded.snooze == snooze_record()

    def test_the_mirror_refuses_a_snoozed_row_without_a_record(
        self, tmp_path: Path
    ) -> None:
        conn = db_mod.init_db(tmp_path / "beads.db")
        try:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO issues "
                    "(id, title, status, issue_type, created_at, updated_at) "
                    "VALUES ('sase-a3', 'Bare', 'snoozed', 'task', 'now', 'now')"
                )
        finally:
            conn.close()

    def test_a_pre_snooze_mirror_migrates_without_losing_close_history(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "beads.db"
        legacy_schema = (
            db_mod._SCHEMA.replace(", 'snoozed'", "")
            .replace("    snooze      TEXT,\n", "")
            .replace("    CHECK(status != 'snoozed' OR issue_type = 'task'),\n", "")
            .replace(
                "    CHECK((status = 'snoozed') = (snooze IS NOT NULL)),\n",
                "",
            )
        )
        conn = sqlite3.connect(db_path)
        conn.executescript(legacy_schema)
        conn.execute(
            "INSERT INTO issues "
            "(id, title, status, issue_type, created_at, updated_at, close_history) "
            "VALUES ('sase-a4', 'Legacy', 'ready', 'task', 'now', 'now', ?)",
            (json.dumps([{"closed_at": "then"}]),),
        )
        conn.commit()
        conn.close()

        migrated = db_mod.init_db(db_path)
        try:
            history: str = migrated.execute(
                "SELECT close_history FROM issues WHERE id='sase-a4'"
            ).fetchone()[0]
            migrated.execute(
                "UPDATE issues SET status='snoozed', snooze=? WHERE id='sase-a4'",
                (json.dumps(snooze_to_dict(snooze_record())),),
            )
            reloaded = db_mod.get_issue(migrated, "sase-a4")
        finally:
            migrated.close()

        assert json.loads(history) == [{"closed_at": "then"}]
        assert reloaded is not None
        assert reloaded.snooze == snooze_record()
