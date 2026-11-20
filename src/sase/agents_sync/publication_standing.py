"""Standing publication-failure alerts with backoff.

Failures are keyed by ``(project, signature)`` in
``~/.sase/agent_publication/standing_alerts.json``. The Rust core (see
:mod:`sase.core.agent_publication_standing`) decides each tick's transition;
this module owns the durable store, observation building, backoff gating,
and one-per-alert notifications.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import logging
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from sase.agents_sync.io import atomic_write_json
from sase.core.agent_publication_standing import (
    STANDING_KINDS,
    STANDING_TRANSITION_CHANGED,
    STANDING_TRANSITION_CLEARED,
    STANDING_TRANSITION_ESCALATED,
    STANDING_TRANSITION_NONE,
    STANDING_TRANSITION_OPENED,
    StandingAlert,
    StandingDecision,
    decide_publication_standing,
)
from sase.core.paths import sase_home
from sase.notification_gates.durability import file_lock

log = logging.getLogger(__name__)

STANDING_ALERTS_FILENAME = "standing_alerts.json"
STANDING_ALERTS_SCHEMA_VERSION = 1
MAX_STANDING_DETAIL_CHARS = 500
STANDING_NOTIFICATION_SENDER = "agent-publication"

_REPORTED_TRANSITIONS = frozenset(
    {
        STANDING_TRANSITION_OPENED,
        STANDING_TRANSITION_CHANGED,
        STANDING_TRANSITION_ESCALATED,
    }
)

_logged_store_failures: set[str] = set()


def _log_store_failure_once(key: str, message: str) -> None:
    if key in _logged_store_failures:
        return
    _logged_store_failures.add(key)
    log.warning("%s", message)


def _standing_alerts_path() -> Path:
    """Return the machine-wide standing-alert store path without touching disk."""

    return sase_home() / "agent_publication" / STANDING_ALERTS_FILENAME


def _alert_key(project: str, signature: str) -> tuple[str, str]:
    return (project, signature)


@dataclass(frozen=True)
class StandingReport:
    """One tick's outcome for a single observation or clear.

    Reported transitions (opened, changed, escalated) and fallbacks count
    one error each with ``detail`` as the legacy diagnostic text; cleared
    only fires the quiet +1 note.
    """

    transition: str
    failure_kind: str
    detail: str
    attempts: int
    alert: StandingAlert | _StoredStandingAlert | None


@dataclass
class _StoredStandingAlert:
    """One durable standing alert row, mirroring the Rust alert wire."""

    project: str
    signature: str
    failure_kind: str
    error_class: str
    detail: str
    attempts: int
    first_seen: float
    last_seen: float
    last_reported: float
    escalated: bool
    next_attempt_at: float
    project_scoped: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "signature": self.signature,
            "failure_kind": self.failure_kind,
            "error_class": self.error_class,
            "detail": self.detail,
            "attempts": self.attempts,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "last_reported": self.last_reported,
            "escalated": self.escalated,
            "next_attempt_at": self.next_attempt_at,
            "project_scoped": self.project_scoped,
        }


def _stored_from_decided(alert: StandingAlert) -> _StoredStandingAlert:
    return _StoredStandingAlert(
        project=alert.project,
        signature=alert.signature,
        failure_kind=alert.failure_kind,
        error_class=alert.error_class,
        detail=alert.detail,
        attempts=alert.attempts,
        first_seen=alert.first_seen,
        last_seen=alert.last_seen,
        last_reported=alert.last_reported,
        escalated=alert.escalated,
        next_attempt_at=alert.next_attempt_at,
        project_scoped=alert.project_scoped,
    )


def _parse_stored(raw: Any) -> _StoredStandingAlert | None:
    if not isinstance(raw, dict):
        return None
    text_fields = ("project", "signature", "failure_kind")
    if any(not isinstance(raw.get(key), str) for key in text_fields):
        return None
    if raw["failure_kind"] not in STANDING_KINDS:
        return None
    numeric_fields = ("first_seen", "last_seen", "last_reported", "next_attempt_at")
    if any(not isinstance(raw.get(key), (int, float)) for key in numeric_fields):
        return None
    attempts = raw.get("attempts")
    if not isinstance(attempts, int) or isinstance(attempts, bool):
        return None
    if not isinstance(raw.get("escalated"), bool):
        return None
    if not isinstance(raw.get("project_scoped"), bool):
        return None
    error_class = raw.get("error_class", "")
    detail = raw.get("detail", "")
    if not isinstance(error_class, str) or not isinstance(detail, str):
        return None
    return _StoredStandingAlert(
        project=raw["project"],
        signature=raw["signature"],
        failure_kind=raw["failure_kind"],
        error_class=error_class,
        detail=detail,
        attempts=attempts,
        first_seen=float(raw["first_seen"]),
        last_seen=float(raw["last_seen"]),
        last_reported=float(raw["last_reported"]),
        escalated=bool(raw["escalated"]),
        next_attempt_at=float(raw["next_attempt_at"]),
        project_scoped=bool(raw["project_scoped"]),
    )


def load_standing_alerts() -> dict[tuple[str, str], _StoredStandingAlert]:
    """Load stored alerts, failing open to ``{}`` on any store trouble.

    A corrupt or unreadable store is quarantined aside (``*.corrupt-<ts>``)
    and logged once per process, so persistence trouble never hides a
    failing project behind an empty alert set.
    """

    path = _standing_alerts_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _quarantine_corrupt_store(path, f"unreadable: {exc}")
        return {}
    if not isinstance(payload, dict):
        _quarantine_corrupt_store(path, "payload is not an object")
        return {}
    if payload.get("schema_version") != STANDING_ALERTS_SCHEMA_VERSION:
        _quarantine_corrupt_store(
            path, f"unsupported schema_version {payload.get('schema_version')!r}"
        )
        return {}
    raw_alerts = payload.get("alerts")
    if not isinstance(raw_alerts, dict):
        _quarantine_corrupt_store(path, "alerts is not an object")
        return {}
    alerts: dict[tuple[str, str], _StoredStandingAlert] = {}
    for key, raw in raw_alerts.items():
        stored = _parse_stored(raw)
        parts = key.split("\x00")
        if (
            stored is None
            or len(parts) != 2
            or (stored.project, stored.signature) != (parts[0], parts[1])
        ):
            _quarantine_corrupt_store(path, f"invalid alert entry {key!r}")
            return {}
        alerts[_alert_key(stored.project, stored.signature)] = stored
    return alerts


def _quarantine_corrupt_store(path: Path, reason: str) -> None:
    _log_store_failure_once(
        "corrupt",
        f"publication standing store {path} {reason}; failing open to no alerts",
    )
    try:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        path.rename(path.with_name(f"{path.name}.corrupt-{stamp}"))
    except OSError as exc:
        _log_store_failure_once(
            "quarantine",
            f"could not quarantine corrupt standing store {path}: {exc}",
        )


def save_standing_alerts(
    alerts: Mapping[tuple[str, str], _StoredStandingAlert],
) -> bool:
    """Persist alerts under the store lock; fail open with ``False`` on error."""

    path = _standing_alerts_path()
    payload = {
        "schema_version": STANDING_ALERTS_SCHEMA_VERSION,
        "alerts": {
            f"{alert.project}\x00{alert.signature}": alert.to_dict()
            for alert in alerts.values()
        },
    }
    try:
        with file_lock(path.with_suffix(path.suffix + ".lock")):
            atomic_write_json(path, payload)
    except Exception as exc:  # noqa: BLE001 - persistence trouble fails open.
        _log_store_failure_once(
            "save", f"could not save publication standing store {path}: {exc}"
        )
        return False
    return True


def _stored_to_previous(stored: _StoredStandingAlert) -> dict[str, Any]:
    return {
        "project": stored.project,
        "signature": stored.signature,
        "failure_kind": stored.failure_kind,
        "error_class": stored.error_class,
        "detail": stored.detail,
        "attempts": stored.attempts,
        "first_seen": stored.first_seen,
        "last_seen": stored.last_seen,
        "last_reported": stored.last_reported,
        "escalated": stored.escalated,
        "next_attempt_at": stored.next_attempt_at,
        "project_scoped": stored.project_scoped,
    }


def _build_observation(
    project: str,
    failure_kind: str,
    detail: str,
) -> dict[str, Any] | None:
    """Build one standing observation, or ``None`` when classification fails.

    The signature comes from the error-groups normalizer so volatile tokens
    never split one cause; the class comes from Rust publication error
    classification. A ``None`` return keeps the tick on today's counting so
    classifier trouble fails open to visible errors.
    """

    if failure_kind not in STANDING_KINDS:
        _log_store_failure_once(
            f"kind:{failure_kind}",
            f"unknown publication standing failure kind {failure_kind!r}",
        )
        return None
    try:
        from sase.core.axe_error_facade import normalize_error_signature
        from sase.core.agent_publication_recovery_publication import (
            classify_publication_error,
        )

        text = detail.strip() or failure_kind
        signature = normalize_error_signature(text)
        error_class = classify_publication_error(text)
    except Exception as exc:  # noqa: BLE001 - fail open to today's counting.
        _log_store_failure_once(
            "classify",
            f"could not classify publication failure for standing: {exc}",
        )
        return None
    if not signature:
        return None
    return {
        "project": project,
        "signature": signature,
        "failure_kind": failure_kind,
        "error_class": error_class,
        "detail": text[:MAX_STANDING_DETAIL_CHARS],
    }


def apply_project_observations(
    alerts: dict[tuple[str, str], _StoredStandingAlert],
    project: str,
    observations: list[tuple[str, str]],
    *,
    now: float | None = None,
    clean: bool = False,
) -> list[StandingReport]:
    """Fold one tick's observations into the store.

    Each ``(failure_kind, detail)`` observation becomes or updates the
    ``(project, signature)`` alert for its normalized signature. Reported
    transitions (opened, changed, escalated) and observations that fail to
    classify (counted directly, exactly like today) are returned; unchanged
    ticks update attempt counts silently. When *clean* is true and no
    observation was recorded, open alerts for *project* transition to
    cleared (returned with their last stored row for the quiet +1 note).
    Alerts for *project* with no matching observation also clear once at
    least one observation classified, so a signature change clears the old
    alert while opening the new one.
    """

    observed = now if now is not None else time.time()
    reported: list[StandingReport] = []
    seen: set[tuple[str, str]] = set()
    for failure_kind, detail in observations:
        observation = _build_observation(project, failure_kind, detail)
        if observation is None:
            reported.append(
                StandingReport(
                    transition=STANDING_TRANSITION_NONE,
                    failure_kind=failure_kind,
                    detail=detail,
                    attempts=0,
                    alert=None,
                )
            )
            continue
        key = _alert_key(project, observation["signature"])
        seen.add(key)
        previous = alerts.get(key)
        try:
            decision: StandingDecision = decide_publication_standing(
                _stored_to_previous(previous) if previous is not None else None,
                observation,
                now=observed,
            )
        except Exception as exc:  # noqa: BLE001 - fail open to today's counting.
            _log_store_failure_once(
                "decide", f"publication standing decider failed for {project}: {exc}"
            )
            reported.append(
                StandingReport(
                    transition=STANDING_TRANSITION_NONE,
                    failure_kind=failure_kind,
                    detail=detail,
                    attempts=0,
                    alert=None,
                )
            )
            continue
        if decision.alert is not None:
            alerts[key] = _stored_from_decided(decision.alert)
            attempts = decision.alert.attempts
        else:
            attempts = previous.attempts if previous is not None else 0
        if decision.transition in _REPORTED_TRANSITIONS:
            if decision.alert is None:
                continue
            reported.append(
                StandingReport(
                    transition=decision.transition,
                    failure_kind=decision.alert.failure_kind,
                    detail=decision.alert.detail,
                    attempts=attempts,
                    alert=decision.alert,
                )
            )
    # Alerts for this project with no observation this tick get their absence:
    # a signature change clears the old alert while opening the new one. When
    # every observation failed to classify, nothing is seen, so nothing is
    # cleared and the failure stays loud instead of flapping.
    if seen or (clean and not observations):
        for key in [key for key in alerts if key[0] == project and key not in seen]:
            previous = alerts[key]
            try:
                clear_decision: StandingDecision = decide_publication_standing(
                    _stored_to_previous(previous), None, now=observed
                )
            except Exception as exc:  # noqa: BLE001 - keep the alert on trouble.
                _log_store_failure_once(
                    "decide",
                    f"publication standing decider failed for {project}: {exc}",
                )
                continue
            if clear_decision.transition == STANDING_TRANSITION_CLEARED:
                del alerts[key]
                reported.append(
                    StandingReport(
                        transition=STANDING_TRANSITION_CLEARED,
                        failure_kind=previous.failure_kind,
                        detail=previous.detail,
                        attempts=previous.attempts,
                        alert=previous,
                    )
                )
    return reported


def repeat_blocked_ticks(
    alerts: dict[tuple[str, str], _StoredStandingAlert],
    project: str,
    *,
    now: float | None = None,
) -> list[StandingReport]:
    """Count one skipped tick against each blocking alert.

    While a project-scoped alert backs off, the drain is skipped, so there
    is no fresh observation; repeating the stored observation keeps true
    attempt counts and still escalates once after 24 h. Returns reported
    transitions (at most escalations).
    """

    observed = now if now is not None else time.time()
    reported: list[StandingReport] = []
    for key in [key for key in alerts if key[0] == project]:
        stored = alerts[key]
        if not stored.project_scoped or stored.next_attempt_at <= observed:
            continue
        observation = {
            "project": stored.project,
            "signature": stored.signature,
            "failure_kind": stored.failure_kind,
            "error_class": stored.error_class,
            "detail": stored.detail,
        }
        try:
            decision: StandingDecision = decide_publication_standing(
                _stored_to_previous(stored), observation, now=observed
            )
        except Exception as exc:  # noqa: BLE001 - keep the alert on trouble.
            _log_store_failure_once(
                "decide", f"publication standing decider failed for {project}: {exc}"
            )
            continue
        if decision.alert is not None:
            alerts[key] = _stored_from_decided(decision.alert)
        if decision.transition in _REPORTED_TRANSITIONS:
            if decision.alert is None:
                continue
            reported.append(
                StandingReport(
                    transition=decision.transition,
                    failure_kind=decision.alert.failure_kind,
                    detail=decision.alert.detail,
                    attempts=decision.alert.attempts,
                    alert=decision.alert,
                )
            )
    return reported


def blocking_alerts(
    alerts: Mapping[tuple[str, str], _StoredStandingAlert],
    project: str,
    now: float,
) -> list[_StoredStandingAlert]:
    """Return open project-scoped alerts whose backoff has not elapsed."""

    return [
        alert
        for (owner, _), alert in alerts.items()
        if owner == project and alert.project_scoped and alert.next_attempt_at > now
    ]


def is_due(
    alerts: Mapping[tuple[str, str], _StoredStandingAlert],
    project: str,
    now: float,
) -> bool:
    """Return whether *project* may drain and ring now."""

    return not blocking_alerts(alerts, project, now)


def has_open_alert_of_kind(
    alerts: Mapping[tuple[str, str], _StoredStandingAlert],
    project: str,
    failure_kind: str,
) -> bool:
    """Return whether *project* already has an open alert of *failure_kind*."""

    return any(
        owner == project and alert.failure_kind == failure_kind
        for (owner, _), alert in alerts.items()
    )


def project_standing_stats(
    alerts: Mapping[tuple[str, str], _StoredStandingAlert],
    project: str,
) -> dict[str, Any]:
    """Summarize open alerts for one project for the publisher heartbeat."""

    owned = [alert for (owner, _), alert in alerts.items() if owner == project]
    due_at = [alert.next_attempt_at for alert in owned if alert.project_scoped]
    return {
        "standing_open": len(owned),
        "standing_signatures": sorted({alert.signature for alert in owned}),
        "standing_next_attempt_at": min(due_at) if due_at else None,
    }


def open_alert_count(
    alerts: Mapping[tuple[str, str], _StoredStandingAlert],
) -> int:
    """Return the total number of open standing alerts."""

    return len(alerts)


def _standing_dedup_key(project: str, signature: str) -> str:
    """Return the per-alert notification dedup key."""

    digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:16]
    return f"agent-publication-standing:{project}:{digest}"


def report_standing_transition(
    report: StandingReport,
    *,
    now: float | None = None,
) -> None:
    """Fire the one notification for a reported transition.

    Unchanged ticks never reach this function, so the notification store is
    rewritten only on transitions. Fallback reports carry no alert and never
    touch notifications; the caller counts them directly. Notification
    trouble is logged and never retries the drain.
    """

    if report.alert is None or report.transition not in (
        STANDING_TRANSITION_OPENED,
        STANDING_TRANSITION_CHANGED,
        STANDING_TRANSITION_ESCALATED,
        STANDING_TRANSITION_CLEARED,
    ):
        return
    project = report.alert.project
    observed = now if now is not None else time.time()
    timestamp = datetime.fromtimestamp(observed, tz=UTC).isoformat()
    try:
        if report.transition == STANDING_TRANSITION_CLEARED:
            _append_cleared_plus_one(project, report.alert, timestamp)
        elif report.transition == STANDING_TRANSITION_ESCALATED:
            _append_escalated_plus_one(project, report.alert, timestamp)
        else:
            _upsert_alert_notification(
                project, report.alert, report.transition, timestamp
            )
    except Exception as exc:  # noqa: BLE001 - notification failure retries nothing.
        log.warning(
            "Could not store publication standing notification for %s: %s",
            project,
            exc,
        )


def _alert_notes(
    project: str, alert: _StoredStandingAlert | StandingAlert, transition: str
) -> list[str]:
    attempts = getattr(alert, "attempts", 0)
    detail = getattr(alert, "detail", "")
    lines = [
        f"Agent publication {transition} for {project}: "
        f"{alert.failure_kind} (attempt {attempts})",
    ]
    if detail:
        lines.append(detail)
    return lines


def _upsert_alert_notification(
    project: str,
    alert: _StoredStandingAlert | StandingAlert,
    transition: str,
    timestamp: str,
) -> None:
    from sase.notifications.models import Notification, normalize_notification_tags
    from sase.notifications.store import upsert_notification

    dedup_key = _standing_dedup_key(project, alert.signature)
    notification = Notification(
        id=str(uuid4()),
        timestamp=timestamp,
        sender=STANDING_NOTIFICATION_SENDER,
        icon="!",
        color="#D14343",
        notes=_alert_notes(project, alert, transition),
        tags=normalize_notification_tags(["agents-sync", "publication", "error"]),
        dedup_key=dedup_key,
    )
    # A dedup key requires a +1 note for the on-match branch; on the create
    # branch the row is minted from the notification above.
    if transition == STANDING_TRANSITION_CHANGED:
        note = (
            f"changed: {alert.failure_kind} (attempt {getattr(alert, 'attempts', 0)})"
        )
    else:
        note = (
            f"still failing: {alert.failure_kind} "
            f"(attempt {getattr(alert, 'attempts', 0)})"
        )
    upsert_notification(
        notification,
        plus_one_note=note,
        plus_one_timestamp=timestamp,
    )


def _append_escalated_plus_one(
    project: str, alert: _StoredStandingAlert | StandingAlert, timestamp: str
) -> None:
    from sase.notifications.store import append_notification_plus_one

    outcome = append_notification_plus_one(
        note=f"escalated after 24h: {alert.failure_kind} "
        f"(attempt {getattr(alert, 'attempts', 0)})",
        sender=STANDING_NOTIFICATION_SENDER,
        timestamp=timestamp,
        dedup_key=_standing_dedup_key(project, alert.signature),
    )
    if getattr(outcome, "action", None) == "no_match":
        _upsert_alert_notification(
            project, alert, STANDING_TRANSITION_ESCALATED, timestamp
        )


def _append_cleared_plus_one(
    project: str, alert: _StoredStandingAlert | StandingAlert, timestamp: str
) -> None:
    from sase.notifications.store import append_notification_plus_one

    # Cleared updates the row without creating a new unread row; when the row
    # is already gone there is nothing to update.
    append_notification_plus_one(
        note=f"cleared at {timestamp}",
        sender=STANDING_NOTIFICATION_SENDER,
        timestamp=timestamp,
        dedup_key=_standing_dedup_key(project, alert.signature),
    )


__all__ = [
    "MAX_STANDING_DETAIL_CHARS",
    "STANDING_ALERTS_FILENAME",
    "STANDING_ALERTS_SCHEMA_VERSION",
    "STANDING_NOTIFICATION_SENDER",
    "StandingReport",
    "apply_project_observations",
    "blocking_alerts",
    "has_open_alert_of_kind",
    "is_due",
    "load_standing_alerts",
    "open_alert_count",
    "project_standing_stats",
    "repeat_blocked_ticks",
    "report_standing_transition",
    "save_standing_alerts",
]
