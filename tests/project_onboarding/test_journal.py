"""Tests for atomic ownership journals."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import stat

import pytest

from sase.project_onboarding.journal import (
    _journal_path,
    journals_dir,
    list_incomplete,
    lookup_journal,
    ownership_facts,
    record_intent,
    record_remote,
    set_journal_status,
    update_management,
    update_step,
)


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(home))
    return home


def _intent(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identity_key": "github.com/sase-org/bob",
        "ref": "sase-org/bob",
        "display": "sase-org/bob",
        "workflow_type": "gh",
        "mode": "add",
        "intent_fingerprint": "abc123",
    }
    payload.update(overrides)
    return payload


class TestJournal:
    def test_record_intent_is_atomic_and_private(self, isolated_home: Path) -> None:
        del isolated_home
        record = record_intent(**_intent())
        path = _journal_path("github.com/sase-org/bob", "sase-org/bob")
        assert path.is_file()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert list(path.parent.glob(".*.tmp")) == []
        assert record["status"] == "running"
        assert record["management"]["pushed"] is False
        assert record["management"]["marker_written"] is False
        assert lookup_journal("github.com/sase-org/bob")["ref"] == "sase-org/bob"

    def test_list_incomplete_preserves_discovery_wire(
        self, isolated_home: Path
    ) -> None:
        journals = isolated_home / "project_onboarding" / "journals"
        journals.mkdir(parents=True)
        (journals / "forge.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "identity_key": "github.com/sase-org/forge",
                    "ref": "sase-org/forge",
                    "display": "sase-org/forge",
                    "status": "running",
                }
            ),
            encoding="utf-8",
        )
        rows = list_incomplete()
        assert rows == [
            {
                "identity_key": "github.com/sase-org/forge",
                "ref": "sase-org/forge",
                "display": "sase-org/forge",
                "status": "running",
                "stopped_at": "",
                "updated_at": "",
            }
        ]

    def test_malformed_journals_are_skipped(self, isolated_home: Path) -> None:
        path = journals_dir()
        path.mkdir(parents=True)
        (path / "bad.json").write_text("{not json", encoding="utf-8")
        (path / "list.json").write_text("[]", encoding="utf-8")
        assert list_incomplete() == []
        assert lookup_journal("github.com/sase-org/bob") is None

    def test_ownership_requires_identity_and_fingerprint(
        self, isolated_home: Path
    ) -> None:
        del isolated_home
        record_intent(**_intent())
        assert ownership_facts("github.com/sase-org/bob", "abc123") is not None
        assert ownership_facts("github.com/sase-org/bob", "other") is None
        assert ownership_facts("github.com/other/bob", "abc123") is None

    def test_management_ownership_requires_active_matching_intent_and_exact_bytes(
        self, isolated_home: Path
    ) -> None:
        del isolated_home
        identity = "github.com/sase-org/bob"
        record_intent(**_intent(setup_required=True))
        update_management(
            identity,
            "abc123",
            display="sase-org/bob",
            stage="write_started",
            baseline_config_hash="before",
            expected_config_hash="expected",
            marker_write_stage="write_started",
        )

        owned = ownership_facts(identity, "abc123", current_config_hash="expected")
        assert owned is not None
        assert owned["setup_required"] is True
        assert owned["management_incomplete"] is True
        assert owned["config_changes_owned"] is True
        changed = ownership_facts(identity, "abc123", current_config_hash="other")
        assert changed is not None
        assert changed["management_incomplete"] is True
        assert changed["config_changes_owned"] is False
        assert (
            ownership_facts(identity, "stale", current_config_hash="expected") is None
        )

    def test_completed_journal_does_not_grant_management_recovery_facts(
        self, isolated_home: Path
    ) -> None:
        del isolated_home
        identity = "github.com/sase-org/bob"
        record_intent(**_intent(setup_required=True))
        update_management(
            identity,
            "abc123",
            stage="write_started",
            baseline_config_hash="before",
            expected_config_hash="expected",
            marker_write_stage="write_started",
        )
        set_journal_status(identity, "complete")

        facts = ownership_facts(identity, "abc123", current_config_hash="expected")
        assert facts is not None
        assert "setup_required" not in facts
        assert facts["management_incomplete"] is False
        assert facts["config_changes_owned"] is False

    def test_update_step_preserves_failed_evidence(self, isolated_home: Path) -> None:
        del isolated_home
        record_intent(**_intent())
        update_step(
            "github.com/sase-org/bob",
            "manage",
            status="failed",
            message="push rejected",
            display="sase-org/bob",
        )
        stored = lookup_journal("github.com/sase-org/bob")
        assert stored is not None
        assert stored["status"] == "failed"
        assert stored["stopped_step"] == "manage"
        assert stored["steps"]["manage"]["message"] == "push rejected"
        record_intent(**_intent())
        stored = lookup_journal("github.com/sase-org/bob")
        assert stored is not None
        assert stored["steps"]["manage"]["message"] == "push rejected"

    def test_record_intent_reuses_path_when_display_changes(
        self, isolated_home: Path
    ) -> None:
        record_intent(**_intent(display="sase-org/bob"))
        original = _journal_path("github.com/sase-org/bob", "sase-org/bob")
        assert original.is_file()
        record_intent(**_intent(display="bob-renamed"))
        stored = lookup_journal("github.com/sase-org/bob")
        assert stored is not None
        assert stored["display"] == "bob-renamed"
        journals = list(
            (isolated_home / "project_onboarding" / "journals").glob("*.json")
        )
        assert journals == [original]

    def test_record_remote_sets_created_and_repo_id(self, isolated_home: Path) -> None:
        del isolated_home
        record_intent(**_intent())
        stored = record_remote(
            "github.com/sase-org/bob",
            repo_id="R1",
            display="sase-org/bob",
            ref="/custom/bob.git",
            adopted_identity_key="git:/custom/bob.git",
            adopted_checkout_dir="/work/bob/",
        )
        assert stored["remote"]["created"] is True
        assert stored["remote"]["repo_id"] == "R1"
        assert stored["remote"]["created_at"]
        assert stored["identity_key"] == "github.com/sase-org/bob"
        assert stored["ref"] == "sase-org/bob"
        assert stored["remote"]["adopted_ref"] == "/custom/bob.git"
        assert stored["remote"]["adopted_identity_key"] == "git:/custom/bob.git"
        assert stored["remote"]["adopted_checkout_dir"] == "/work/bob/"
        facts = ownership_facts("github.com/sase-org/bob", "abc123")
        assert facts is not None
        assert facts["remote_created"] is True
        assert facts["repo_id"] == "R1"

    def test_complete_journals_older_than_30_days_are_pruned(
        self, isolated_home: Path
    ) -> None:
        del isolated_home
        record_intent(**_intent(identity_key="github.com/sase-org/old", display="old"))
        set_journal_status("github.com/sase-org/old", "complete", display="old")
        path = _journal_path("github.com/sase-org/old", "old")
        payload = json.loads(path.read_text(encoding="utf-8"))
        old = (datetime.now(UTC) - timedelta(days=31)).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload["updated_at"] = old
        path.write_text(json.dumps(payload), encoding="utf-8")
        record_intent(**_intent())
        assert not path.exists()
        assert lookup_journal("github.com/sase-org/bob") is not None
