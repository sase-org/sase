"""Tests for agent publication doctor issue grouping and standing alerts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.agents_sync.publication_outbox import AgentPublicationOutboxItem
from sase.doctor.checks_agent_publication_outbox import check_agent_publication_outbox
from tests.doctor._checks_agent_publication_helpers import (
    doctor_context,
    make_item,
    make_record,
    write_outbox,
)


def test_agent_publication_outbox_doctor_groups_one_cause_into_one_issue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = make_record(tmp_path)
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication_outbox.list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    now = 10_000.0
    rows = [
        make_item(
            local_agent="one--code",
            revision="a" * 40,
            attempts=3,
            last_error="drain failed for run abcdef1234567890: connection timed out",
            quarantined=True,
            created_at=now - 300,
            updated_at=now - 60,
        ),
        make_item(
            local_agent="two--code",
            revision="b" * 40,
            attempts=5,
            last_error="drain failed for run 0987654321fedcba: connection timed out",
            quarantined=True,
            created_at=now - 200,
            updated_at=now - 30,
        ),
        make_item(
            local_agent="three--code",
            revision="c" * 40,
            attempts=3,
            last_error="git pull --rebase failed",
            quarantined=True,
            created_at=now - 200,
            updated_at=now - 30,
        ),
    ]
    write_outbox(tmp_path / ".sase", "alpha", rows)

    first = check_agent_publication_outbox(
        doctor_context(tmp_path),
        now=now,
        stalled_attempts=3,
        stalled_age_seconds=24 * 60 * 60,
    )

    assert first.status == "WARN"
    assert "2 agent publication issue group(s)" in first.summary
    assert len(first.data["groups"]) == 2
    [timeout_group] = [
        group for group in first.data["groups"] if group["request_count"] == 2
    ]
    assert timeout_group["total_attempts"] == 8
    assert timeout_group["first_time"] == now - 300
    assert timeout_group["last_time"] == now - 30
    # The grouped issue line still names its reason and the newest member's
    # actual error, so grouping never hides why a cause needs attention.
    [timeout_detail] = [
        detail for detail in first.details if "2 request(s) (quarantined)" in detail
    ]
    assert "; quarantined; last error: drain failed for run 0987654321fedcba" in (
        timeout_detail
    )

    # A later tick with bumped attempts but unchanged causes keeps the count.
    later_rows = [
        {**row, "attempts": row["attempts"] + 4, "updated_at": now + 900}
        for row in rows
    ]
    outbox_path = (
        tmp_path / ".sase" / "projects" / "alpha" / "agents-publication-outbox.json"
    )
    outbox_path.write_text(
        json.dumps({"schema_version": 2, "items": later_rows}),
        encoding="utf-8",
    )
    second = check_agent_publication_outbox(
        doctor_context(tmp_path),
        now=now + 900,
        stalled_attempts=3,
        stalled_age_seconds=24 * 60 * 60,
    )

    assert "2 agent publication issue group(s)" in second.summary
    assert len(second.data["groups"]) == 2


def test_agent_publication_outbox_doctor_surfaces_standing_alerts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.doctor._agent_publication import _outbox_signature_for

    record = make_record(tmp_path)
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication_outbox.list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    now = 10_000.0
    row = make_item(
        local_agent="bad--code",
        revision="b" * 40,
        attempts=7,
        last_error="git pull --rebase failed",
        quarantined=True,
        created_at=now - 120,
        updated_at=now - 60,
    )
    write_outbox(tmp_path / ".sase", "alpha", [row])
    signature = _outbox_signature_for(
        AgentPublicationOutboxItem(**{k: v for k, v in row.items() if k != "id"})
    )
    store = tmp_path / ".sase" / "agent_publication" / "standing_alerts.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "alerts": {
                    f"alpha\x00{signature}": {
                        "project": "alpha",
                        "signature": signature,
                        "failure_kind": "drain_error",
                        "error_class": "rebase_conflict",
                        "detail": "git pull --rebase failed",
                        "attempts": 7,
                        "first_seen": now - 120,
                        "last_seen": now - 60,
                        "last_reported": now - 60,
                        "escalated": False,
                        "next_attempt_at": now + 60,
                        "project_scoped": True,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    check = check_agent_publication_outbox(
        doctor_context(tmp_path),
        now=now,
        stalled_attempts=3,
        stalled_age_seconds=24 * 60 * 60,
    )

    assert check.data["standing_alert_count"] == 1
    assert check.data["standing_alerts"][0]["attempts"] == 7
    [group] = check.data["groups"]
    assert group["standing"]["attempts"] == 7
    assert group["standing"]["failure_kind"] == "drain_error"


def test_agent_publication_outbox_doctor_ignores_unreadable_standing_store(
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
                last_error="git pull --rebase failed",
                quarantined=True,
                created_at=now - 120,
                updated_at=now - 60,
            )
        ],
    )
    store = tmp_path / ".sase" / "agent_publication" / "standing_alerts.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("{not json", encoding="utf-8")

    check = check_agent_publication_outbox(
        doctor_context(tmp_path),
        now=now,
        stalled_attempts=3,
        stalled_age_seconds=24 * 60 * 60,
    )

    assert check.status == "WARN"
    assert "1 agent publication issue group(s)" in check.summary
    assert check.data["standing_alert_count"] == 0
    assert "standing" not in check.data["groups"][0]
    assert store.read_text(encoding="utf-8") == "{not json"
