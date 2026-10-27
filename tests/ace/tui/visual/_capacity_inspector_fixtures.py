"""Stable reports for the capacity-inspector visual snapshots."""

from __future__ import annotations

from datetime import UTC, datetime

from sase.config.runner_limit_override import (
    EffectiveRunnerLimitSnapshot,
    TemporaryRunnerLimitOverride,
)
from tests._runner_slots_helpers import _record
from tests.test_machine_capacity_report import (
    _report_from_records,
    _screenshot_records,
)

NOW = datetime(2026, 7, 12, 12, 3, tzinfo=UTC).timestamp()


def _started(seconds_ago: float) -> str:
    return datetime.fromtimestamp(NOW - seconds_ago, tz=UTC).isoformat()


def screenshot_report():
    """Return the small five-of-eight report used by the original snapshot."""
    return _report_from_records(_screenshot_records(), now=NOW)


def busy_report():
    """Return a deterministic full report with every inspector tier represented."""
    records = [
        _record(
            "/holder-heavy",
            run_started=True,
            run_started_at=_started(3 * 3600 + 12 * 60),
            name="sase-1oa.4",
            queue_weight=2.0,
            queue_weight_explicit=True,
        ),
        *[
            _record(
                f"/worker-{index}",
                run_started=True,
                run_started_at=_started(
                    {1: 50 * 60, 2: 2 * 3600 + 60, 3: 12 * 60, 4: 6 * 60, 5: 4 * 60}[
                        index
                    ]
                ),
                name=(
                    "bob-cli-an.6.6.6.5.6.5.5.6.6.6.6.6.6.6.6.land"
                    if index == 1
                    else f"sase-1nf.14.1.{index}"
                ),
            )
            for index in range(1, 6)
        ],
        _record(
            "/verify-monitor",
            run_started=True,
            run_started_at=_started(18 * 60),
            name="sase-1lou.5.1.3",
            agent_session="verify-session",
            agent_session_role="monitor",
            monitor_id="verify-session-turn",
        ),
        _record(
            "/wait-monitor",
            run_started=True,
            run_started_at=_started(75 * 60),
            name="sase-1n6.10--mon",
            agent_session="wait-session",
            agent_session_role="monitor",
            monitor_id="wait-session-turn",
            queue_weight=0.0,
            queue_weight_explicit=True,
        ),
        _record(
            "/queue-1",
            name="sase-1nf.15",
            requested_at=datetime.fromtimestamp(NOW - 4 * 60, tz=UTC).isoformat(),
            wait_runners=8,
        ),
        _record(
            "/queue-2",
            name="sase-1oc.2",
            requested_at=datetime.fromtimestamp(NOW - 60, tz=UTC).isoformat(),
            wait_runners=8,
        ),
        *[
            _record(f"/waiting-{index}", name=f"waiting-{index}")
            for index in range(1, 4)
        ],
        *[
            _record(f"/inactive-{index}", name=f"inactive-{index}")
            for index in range(1, 5)
        ],
        *[
            _record(
                f"/record-{index}",
                name=f"record-{index}",
                appears_as_agent=False,
            )
            for index in range(1, 6)
        ],
    ]
    report = _report_from_records(
        records,
        now=NOW,
        configured=10,
        override=8,
        is_live=lambda record: not record.artifact_dir.startswith("/inactive-"),
    )

    # Model a serial rider in the report's authoritative accounting output.
    accounting = [dict(entry) for entry in report.accounting]
    accounting.append(
        {
            "artifact_dir": "/verify-rider",
            "agent_name": "sase-1lou.2",
            "project_name": "proj",
            "state": "riding_claim",
            "claim_holder_artifact_dir": "/verify-monitor",
            "claim_owner_key": "verify-session",
            "charged_weight": 0.0,
            "weight_source": "inherited",
            "reason_code": None,
        }
    )
    object.__setattr__(report, "accounting", tuple(accounting))

    waiters = [dict(waiter) for waiter in report.waiters]
    if len(waiters) > 1:
        waiters[1]["blockers"] = [{"code": "hold-barrier", "held_by": "sase-1ob"}]
        waiters[1]["eligible"] = False
    object.__setattr__(report, "waiters", tuple(waiters))

    limit = report.limit
    object.__setattr__(
        report,
        "limit",
        EffectiveRunnerLimitSnapshot(
            configured_limit=limit.configured_limit,
            temporary_override=TemporaryRunnerLimitOverride(
                version=1,
                limit=8,
                created_at=NOW - 44 * 24 * 60 * 60,
                expires_at=None,
                source="ace",
            ),
            captured_at=NOW,
        ),
    )
    return report


def over_limit_report():
    """Return a five-of-one report with a per-launch budget note."""
    return _report_from_records(
        _screenshot_records(),
        now=NOW,
        configured=1,
        override=None,
    )


def blocked_report():
    """Return an invalid-accounting report with an attention row."""
    invalid = _record("/invalid-weight", run_started=True, name="invalid-weight")
    assert invalid.agent_meta is not None
    object.__setattr__(invalid.agent_meta, "queue_weight_invalid", True)
    return _report_from_records([*_screenshot_records(), invalid], now=NOW)
