"""Tests for the flag bead type across the Python surfaces.

The Rust core owns the flag mutations; these tests cover the Python mirror of
the model and the three storage surfaces that have to agree about what a flag
record means: the Rust wire dicts, ``issues.jsonl``, and the compatibility
SQLite mirror.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from sase.bead import db as db_mod
from sase.bead._db_schema import SCHEMA_SQL
from sase.bead.flag_codec import flag_from_dict, flag_to_dict
from sase.bead.jsonl import export_to_jsonl, import_from_jsonl
from sase.bead.model import FlagRecord, Issue, IssueType, Status
from sase.core.bead_wire import issue_from_dict

CREATED_AT = "2026-08-06T09:00:00Z"


def flag_record(**overrides: object) -> FlagRecord:
    fields: dict[str, object] = {
        "key": "demo_key",
        "remove_by_date": "2026-12-01",
        "remove_by_release": "0.19.0",
    }
    fields.update(overrides)
    return FlagRecord(**fields)  # type: ignore[arg-type]


def flag_bead(**overrides: object) -> Issue:
    fields: dict[str, object] = {
        "id": "sase-f1",
        "title": "Retire demo_key",
        "issue_type": IssueType.FLAG,
        "status": Status.OPEN,
        "created_at": CREATED_AT,
        "updated_at": CREATED_AT,
        "flag": flag_record(),
    }
    fields.update(overrides)
    return Issue(**fields)  # type: ignore[arg-type]


class TestFlagRecordValidation:
    def test_valid_record_passes(self) -> None:
        flag_bead().validate()

    @pytest.mark.parametrize(
        "key", ["", " ", "Demo", "demo-key", "_demo", "demo_", "1demo"]
    )
    def test_key_must_be_non_empty_snake_case(self, key: str) -> None:
        issue = flag_bead(flag=flag_record(key=key))

        with pytest.raises(ValueError, match="key must be non-empty snake_case"):
            issue.validate()

    @pytest.mark.parametrize(
        "value", ["", "2026-12-01T00:00:00Z", "2026/12/01", "soon"]
    )
    def test_remove_by_date_must_be_an_iso_date(self, value: str) -> None:
        issue = flag_bead(flag=flag_record(remove_by_date=value))

        with pytest.raises(ValueError, match="remove_by_date must be an ISO date"):
            issue.validate()

    @pytest.mark.parametrize("value", ["", "v0.19.0", "0.19", "latest"])
    def test_remove_by_release_must_be_a_release_string(self, value: str) -> None:
        issue = flag_bead(flag=flag_record(remove_by_release=value))

        with pytest.raises(
            ValueError, match="remove_by_release must be a release string"
        ):
            issue.validate()

    def test_a_prerelease_suffix_is_accepted(self) -> None:
        flag_bead(
            flag=flag_record(key="plugins_enabled", remove_by_release="0.19.0-rc.1")
        ).validate()


class TestFlagTypeValidation:
    def test_flag_issues_must_carry_flag_metadata(self) -> None:
        issue = flag_bead(flag=None)

        with pytest.raises(ValueError, match="flag issues must carry flag metadata"):
            issue.validate()

    def test_only_flag_issues_can_carry_flag_metadata(self) -> None:
        issue = flag_bead(issue_type=IssueType.TASK)

        with pytest.raises(
            ValueError, match="Only flag issues can carry flag metadata"
        ):
            issue.validate()

    def test_flag_issues_cannot_have_a_parent_id(self) -> None:
        issue = flag_bead(parent_id="sase-1")

        with pytest.raises(ValueError, match="Flag issues cannot have a parent_id"):
            issue.validate()

    def test_flag_issues_cannot_carry_plan_tier_metadata(self) -> None:
        from sase.bead.model import BeadTier

        issue = flag_bead(tier=BeadTier.EPIC)

        with pytest.raises(
            ValueError, match="Flag issues cannot carry plan tier metadata"
        ):
            issue.validate()

    def test_flag_issues_still_cannot_have_ready_or_snoozed_status(self) -> None:
        ready = flag_bead(status=Status.READY)
        with pytest.raises(ValueError, match="Only task issues can have ready"):
            ready.validate()

        snoozed = flag_bead(status=Status.SNOOZED)
        with pytest.raises(ValueError, match="Only task issues can have snoozed"):
            snoozed.validate()


class TestFlagCodec:
    def test_wire_dict_round_trips_in_core_field_order(self) -> None:
        encoded = flag_to_dict(flag_record())

        assert list(encoded) == ["key", "remove_by_date", "remove_by_release"]
        assert flag_from_dict(encoded) == flag_record()

    @pytest.mark.parametrize("value", [None, "", [], 3])
    def test_unusable_payloads_decode_to_none(self, value: object) -> None:
        assert flag_from_dict(value) is None


class TestFlagReadFacadeWire:
    def test_issue_from_dict_decodes_the_record(self) -> None:
        issue = issue_from_dict(
            {
                "id": "sase-f1",
                "title": "Retire demo_key",
                "status": "open",
                "issue_type": "flag",
                "flag": flag_to_dict(flag_record()),
            }
        )

        assert issue.issue_type is IssueType.FLAG
        assert issue.flag == flag_record()

    def test_a_row_without_a_flag_key_decodes_to_none(self) -> None:
        issue = issue_from_dict(
            {"id": "sase-a1", "title": "T", "status": "open", "issue_type": "task"}
        )

        assert issue.flag is None


class TestFlagJsonlProjection:
    def test_row_round_trips_and_omits_the_key_when_absent(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "issues.jsonl"
        flagged = flag_bead()
        plain = Issue(
            id="sase-a2",
            title="An ordinary task",
            issue_type=IssueType.TASK,
            status=Status.OPEN,
            created_at=CREATED_AT,
            updated_at=CREATED_AT,
        )

        source = db_mod.init_db(tmp_path / "source.db")
        try:
            db_mod.create_issue(source, flagged)
            db_mod.create_issue(source, plain)
            export_to_jsonl(source, path)
        finally:
            source.close()

        rows = {
            json.loads(line)["id"]: json.loads(line)
            for line in path.read_text().splitlines()
        }

        assert rows["sase-f1"]["flag"] == flag_to_dict(flag_record())
        assert "flag" not in rows["sase-a2"]

        conn = db_mod.init_db(tmp_path / "beads.db")
        try:
            import_from_jsonl(path, conn)
            reloaded = db_mod.get_issue(conn, "sase-f1")
        finally:
            conn.close()

        assert reloaded is not None
        assert reloaded.issue_type is IssueType.FLAG
        assert reloaded.flag == flag_record()


class TestFlagSqliteMirror:
    def test_a_flag_row_survives_a_write_and_read(self, tmp_path: Path) -> None:
        conn = db_mod.init_db(tmp_path / "beads.db")
        try:
            db_mod.create_issue(conn, flag_bead())
            reloaded = db_mod.get_issue(conn, "sase-f1")
        finally:
            conn.close()

        assert reloaded is not None
        assert reloaded.flag == flag_record()

    def test_the_mirror_refuses_a_flag_row_without_a_record(
        self, tmp_path: Path
    ) -> None:
        conn = db_mod.init_db(tmp_path / "beads.db")
        try:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO issues "
                    "(id, title, status, issue_type, created_at, updated_at) "
                    "VALUES ('sase-f2', 'Bare', 'open', 'flag', 'now', 'now')"
                )
        finally:
            conn.close()

    def test_a_pre_flag_mirror_migrates_without_losing_close_history(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "beads.db"
        legacy_schema = (
            SCHEMA_SQL.replace(", 'flag'", "")
            .replace("    flag        TEXT,\n", "")
            .replace(
                " OR\n        (issue_type = 'flag' AND parent_id IS NULL)\n",
                "\n",
            )
            .replace(
                "    CHECK((issue_type = 'flag') = (flag IS NOT NULL)),\n",
                "",
            )
            .replace(" AND issue_type != 'flag'", "")
        )
        assert "'flag'" not in legacy_schema
        conn = sqlite3.connect(db_path)
        conn.executescript(legacy_schema)
        conn.execute(
            "INSERT INTO issues "
            "(id, title, status, issue_type, created_at, updated_at, close_history) "
            "VALUES ('sase-f3', 'Legacy', 'open', 'task', 'now', 'now', ?)",
            (json.dumps([{"closed_at": "then"}]),),
        )
        conn.commit()
        conn.close()

        migrated = db_mod.init_db(db_path)
        try:
            history: str = migrated.execute(
                "SELECT close_history FROM issues WHERE id='sase-f3'"
            ).fetchone()[0]
            migrated.execute(
                "UPDATE issues SET issue_type='flag', flag=? WHERE id='sase-f3'",
                (json.dumps(flag_to_dict(flag_record())),),
            )
            reloaded = db_mod.get_issue(migrated, "sase-f3")
        finally:
            migrated.close()

        assert json.loads(history) == [{"closed_at": "then"}]
        assert reloaded is not None
        assert reloaded.flag == flag_record()
