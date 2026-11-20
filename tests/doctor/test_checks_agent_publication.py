"""Tests for doctor checks over the agent publication outbox."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.agents_sync.publication_outbox import PUBLICATION_OUTBOX_SCHEMA_VERSION
from sase.doctor.checks_agent_publication_outbox import check_agent_publication_outbox
from tests.doctor._checks_agent_publication_helpers import (
    doctor_context,
    make_item,
    make_record,
    write_outbox,
)


def test_agent_publication_outbox_doctor_reports_clean_outbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = make_record(tmp_path)
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication_outbox.list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    write_outbox(tmp_path / ".sase", "alpha", [])

    check = check_agent_publication_outbox(doctor_context(tmp_path), now=200.0)

    assert check.status == "OK"
    assert "no quarantined, stalled, or parked requests" in check.summary
    assert check.data["request_count"] == 0
    assert check.data["quarantined_request_count"] == 0
    assert check.data["stalled_request_count"] == 0
    assert check.data["parked_request_count"] == 0


def test_agent_publication_outbox_doctor_reports_quarantined_and_stalled_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = make_record(tmp_path)
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication_outbox.list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    now = 10_000.0
    write_outbox(
        tmp_path / ".sase",
        "alpha",
        [
            make_item(
                local_agent="bad--code",
                revision="b" * 40,
                attempts=3,
                last_error="committing agent absent from project inventory",
                quarantined=True,
                created_at=now - 120,
                updated_at=now - 60,
            ),
            make_item(
                local_agent="slow--code",
                revision="c" * 40,
                attempts=3,
                last_error="git pull --rebase failed",
                created_at=now - 2 * 24 * 60 * 60,
                updated_at=now - 60,
            ),
        ],
    )

    check = check_agent_publication_outbox(
        doctor_context(tmp_path),
        now=now,
        stalled_attempts=3,
        stalled_age_seconds=24 * 60 * 60,
    )

    assert check.status == "WARN"
    assert "2 agent publication issue group(s)" in check.summary
    assert "1 quarantined, 1 stalled" in check.summary
    assert "sase agent sync --retry-quarantined" in check.summary
    assert "1 request(s) (quarantined)" in check.details[0]
    assert "1 request(s) (stalled)" in check.details[1]
    assert check.next_steps == (
        "Run `sase agent sync --retry-quarantined` to release quarantined requests and retry publication.",
    )
    assert check.data["request_count"] == 2
    assert check.data["quarantined_request_count"] == 1
    assert check.data["stalled_request_count"] == 1
    assert len(check.data["groups"]) == 2
    assert check.data["settled_request_count"] == 0


def test_agent_publication_outbox_doctor_reports_dropped_obsolete_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = make_record(tmp_path)
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication_outbox.list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    write_outbox(
        tmp_path / ".sase",
        "alpha",
        [
            {**make_item(), "kind": "agent_hood", "rank": 0},
            {
                "id": "bead",
                "kind": "bead_pages",
                "rank": 1,
                "project_key": "alpha",
                "project": "Alpha",
                "bead_id": "alpha-1.2",
                "lineage_root": "alpha-1",
                "primary_revision": "e" * 40,
                "attempts": 0,
                "last_error": None,
                "quarantined": False,
                "quarantined_at": None,
                "terminal": False,
                "terminal_reason": None,
                "created_at": 100.0,
                "updated_at": 100.0,
            },
        ],
        schema_version=4,
    )

    check = check_agent_publication_outbox(
        doctor_context(tmp_path),
        now=200.0,
        stalled_attempts=3,
        stalled_age_seconds=24 * 60 * 60,
    )

    assert check.status == "WARN"
    assert "1 obsolete request kind(s) dropped" in check.summary
    assert (
        "dropped 1 obsolete publication request(s) (1 bead_pages)" in (check.details[0])
    )
    assert check.details[0].startswith("alpha: ")
    assert check.next_steps == (
        "Obsolete publication requests were dropped while reading the outbox; run "
        "`sase agent sync --retry-quarantined` to rewrite it at schema "
        f"{PUBLICATION_OUTBOX_SCHEMA_VERSION} and clear this notice.",
    )
    assert check.data["migration_notice_count"] == 1
    assert check.data["request_count"] == 1
    assert check.data["problems"] == ()


def test_agent_publication_outbox_doctor_points_retired_requests_at_the_drop_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = make_record(tmp_path)
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication_outbox.list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    now = 10_000.0
    reason = "hood 'lt' has no publishable runs"
    write_outbox(
        tmp_path / ".sase",
        "alpha",
        [
            make_item(
                local_agent="lt--code",
                revision="d" * 40,
                attempts=2,
                last_error=reason,
                terminal=True,
                terminal_reason=reason,
                created_at=now - 120,
                updated_at=now - 60,
            )
        ],
    )

    check = check_agent_publication_outbox(
        doctor_context(tmp_path),
        now=now,
        stalled_attempts=3,
        stalled_age_seconds=24 * 60 * 60,
    )

    assert check.status == "WARN"
    assert "1 retired" in check.summary
    assert "sase agent sync --drop-retired" in check.summary
    assert "sase agent sync --retry-quarantined" not in check.summary
    assert "1 request(s) (retired)" in check.details[0]
    assert check.next_steps == (
        "Run `sase agent sync --drop-retired` to drop retired requests that can never be published.",
    )
    assert check.data["retired_request_count"] == 1
    assert check.data["quarantined_request_count"] == 0
    assert check.data["stalled_request_count"] == 0
    assert check.data["problems"][0]["remediation_command"] == (
        "sase agent sync --drop-retired"
    )


def test_agent_publication_outbox_doctor_settles_terminal_prompt_archives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = make_record(tmp_path)
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication_outbox.list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    now = 10_000.0
    reason = "prompt_archive_unrecoverable: no local source in any known location"
    write_outbox(
        tmp_path / ".sase",
        "alpha",
        [
            make_item(
                local_agent="gone--code",
                revision="d" * 40,
                attempts=3,
                last_error=reason,
                quarantined=True,
                terminal=True,
                terminal_reason=reason,
                created_at=now - 120,
                updated_at=now - 60,
            )
        ],
    )

    check = check_agent_publication_outbox(
        doctor_context(tmp_path),
        now=now,
        stalled_attempts=3,
        stalled_age_seconds=24 * 60 * 60,
    )

    assert check.status == "OK"
    assert "1 settled terminal (audited)" in check.summary
    assert check.data["settled_request_count"] == 1
    assert check.data["request_count"] == 1
    assert check.data["groups"] == ()
    assert check.data["problems"] == ()
    assert check.data["settled"][0]["terminal_reason"] == reason
    assert check.data["settled"][0]["audit_path"].endswith("terminal_obligations.jsonl")


def test_agent_publication_outbox_doctor_excludes_settled_from_warn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = make_record(tmp_path)
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication_outbox.list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    now = 10_000.0
    reason = "prompt_archive_unrecoverable: no local source in any known location"
    write_outbox(
        tmp_path / ".sase",
        "alpha",
        [
            make_item(
                local_agent="gone--code",
                revision="d" * 40,
                attempts=3,
                last_error=reason,
                quarantined=True,
                terminal=True,
                terminal_reason=reason,
                created_at=now - 120,
                updated_at=now - 60,
            ),
            make_item(
                local_agent="bad--code",
                revision="e" * 40,
                attempts=3,
                last_error="committing agent absent from project inventory",
                quarantined=True,
                created_at=now - 120,
                updated_at=now - 60,
            ),
        ],
    )

    check = check_agent_publication_outbox(
        doctor_context(tmp_path),
        now=now,
        stalled_attempts=3,
        stalled_age_seconds=24 * 60 * 60,
    )

    assert check.status == "WARN"
    assert "1 agent publication issue group(s)" in check.summary
    assert "1 settled terminal (audited)" in check.summary
    assert len(check.details) == 1
    assert check.data["settled_request_count"] == 1
