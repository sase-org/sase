"""Tests for live standing publication alerts reported as doctor issues."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.agents_sync.publication_outbox import AgentPublicationOutboxItem
from sase.diagnostics import DiagnosticCheck
from sase.doctor._agent_publication import _outbox_signature_for
from sase.doctor.checks_agent_publication_outbox import check_agent_publication_outbox
from tests.doctor._checks_agent_publication_helpers import (
    doctor_context,
    make_item,
    make_record,
    write_outbox,
)

_NOW = 10_000.0


def _alert(
    *,
    project: str = "alpha",
    signature: str = "target unavailable: missing primary checkout",
    failure_kind: str = "target_unavailable",
    attempts: int = 4,
    last_seen: float = _NOW - 30,
    next_attempt_at: float = _NOW + 240,
) -> dict[str, object]:
    return {
        "project": project,
        "signature": signature,
        "failure_kind": failure_kind,
        "error_class": "other",
        "detail": f"{project}: primary checkout is missing (pid 4242, age 12s)",
        "attempts": attempts,
        "first_seen": _NOW - 600,
        "last_seen": last_seen,
        "last_reported": _NOW - 600,
        "escalated": False,
        "next_attempt_at": next_attempt_at,
        "project_scoped": True,
    }


def _write_standing_store(tmp_path: Path, *alerts: dict[str, object]) -> Path:
    store = tmp_path / ".sase" / "agent_publication" / "standing_alerts.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "alerts": {
                    f"{alert['project']}\x00{alert['signature']}": alert
                    for alert in alerts
                },
            }
        ),
        encoding="utf-8",
    )
    return store


def _check(tmp_path: Path, *, now: float = _NOW) -> DiagnosticCheck:
    return check_agent_publication_outbox(
        doctor_context(tmp_path),
        now=now,
        stalled_attempts=3,
        stalled_age_seconds=24 * 60 * 60,
    )


@pytest.fixture
def alpha_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    record = make_record(tmp_path)
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication_outbox.list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    return tmp_path


def test_standing_alert_without_rows_is_a_warn_issue(alpha_project: Path) -> None:
    write_outbox(alpha_project / ".sase", "alpha", [])
    store = _write_standing_store(alpha_project, _alert())
    before = store.read_text(encoding="utf-8")

    check = _check(alpha_project)

    assert check.status == "WARN"
    assert "1 agent publication issue group(s)" in check.summary
    assert "1 standing alert(s) without stuck rows" in check.summary
    assert check.data["groups"] == ()
    assert check.data["standing_issue_count"] == 1
    [issue] = check.data["standing_issues"]
    assert issue["backing_off"] is True
    [detail] = check.details
    assert detail.startswith("alpha: standing target_unavailable alert (other)")
    assert "4 attempt(s)" in detail
    assert "first seen 1970-01-01T02:36:40Z (10m 0s ago)" in detail
    assert "last seen 1970-01-01T02:46:10Z (30s ago)" in detail
    assert "backing off until 1970-01-01T02:50:40Z (in 4m 0s)" in detail
    assert "last error: alpha: primary checkout is missing" in detail
    # The read is strictly read-only.
    assert store.read_text(encoding="utf-8") == before


def test_standing_issue_count_stays_flat_across_ticks(alpha_project: Path) -> None:
    write_outbox(alpha_project / ".sase", "alpha", [])
    _write_standing_store(
        alpha_project,
        _alert(),
        _alert(
            project="*publisher*",
            signature="could not list enabled projects",
            failure_kind="selection_error",
            next_attempt_at=_NOW - 1,
        ),
    )
    first = _check(alpha_project)

    # A later tick bumps attempts and last-seen on the same causes; the
    # backoff has elapsed for both.
    later = _NOW + 900
    _write_standing_store(
        alpha_project,
        _alert(attempts=11, last_seen=later - 5, next_attempt_at=later - 1),
        _alert(
            project="*publisher*",
            signature="could not list enabled projects",
            failure_kind="selection_error",
            attempts=60,
            last_seen=later - 5,
            next_attempt_at=later - 1,
        ),
    )
    second = _check(alpha_project, now=later)

    for check in (first, second):
        assert check.status == "WARN"
        assert "2 agent publication issue group(s)" in check.summary
        assert check.data["standing_issue_count"] == 2
    assert [issue["project"] for issue in second.data["standing_issues"]] == [
        "*publisher*",
        "alpha",
    ]
    assert any("11 attempt(s)" in detail for detail in second.details)
    assert all("not backing off" in detail for detail in second.details)


def test_matching_standing_alert_does_not_double_count(alpha_project: Path) -> None:
    row = make_item(
        local_agent="bad--code",
        revision="b" * 40,
        attempts=7,
        last_error="git pull --rebase failed",
        quarantined=True,
        created_at=_NOW - 120,
        updated_at=_NOW - 60,
    )
    write_outbox(alpha_project / ".sase", "alpha", [row])
    signature = _outbox_signature_for(
        AgentPublicationOutboxItem(**{k: v for k, v in row.items() if k != "id"})
    )
    _write_standing_store(
        alpha_project,
        _alert(signature=signature, failure_kind="charged_item_error"),
    )

    check = _check(alpha_project)

    assert check.status == "WARN"
    assert "1 agent publication issue group(s)" in check.summary
    assert "standing alert(s)" not in check.summary
    assert check.data["standing_issue_count"] == 0
    assert check.data["standing_alert_count"] == 1
    [group] = check.data["groups"]
    assert group["standing"]["failure_kind"] == "charged_item_error"
    [detail] = check.details
    assert "standing" not in detail
