"""One upserted amber ``↻`` notification and live report per update episode.

Phase ``episode-notify`` owns the designed experience; phase ``healer`` left
three call sites (:func:`publish_relaunch`, :func:`publish_escalation`, and
:func:`resurface_failure`) whose signatures stay stable here.

Episode row contract (``sender=agent.auto-restart``, ``action=ViewReport``):

- One row per update episode, keyed ``agent-auto-restart:<episode>``. Every
  further relaunch in the episode appends one ``+1`` note; a ``+1`` creates
  no row, so it never toasts.
- Exactly one information toast per episode, on creation. Title refreshes go
  through :func:`reconcile_notification_rows`, which was verified to own
  ``notes`` and ``action_data`` while leaving ``timestamp``/``resurfaced_at``
  (the activity cursor) untouched — so a refresh never re-toasts, re-pushes,
  or resurfaces.
- ``notes[0]`` is the calm title and never contains "fail" or "error";
  exception text appears only in note 2 or later.
- The live report at ``episodes/<slug>.report.json`` is a projection of the
  ledger records carrying the episode id, re-rendered (and validated with
  :func:`validate_chop_report`) on every notify call. The scheduler job and
  the land phase reuse :func:`refresh_episode_report` on settlement.
- A dismissed episode row is never revived: the next restart in that episode
  opens ``<episode>#2``.
- Escalations are loud. Post-provider, declined, probe-failed, and
  replacement-broke-again failures re-surface the agent's own failure
  notification (``sender=user-agent``, ``ViewErrorReport``, Errors bucket)
  with the escalation sentence appended. Only the storm breaker posts as
  ``agent.auto-restart`` at error severity.

Store limits honored here (verified empirically, not assumed): neither the
upsert ``+1`` branch nor the reconcile path merges ``files``, so the row's
``files`` carry the creating agent's evidence while every agent's evidence
is linked from the live report and its inline snapshot.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

SENDER = "agent.auto-restart"
ICON = "↻"
COLOR = "#FFAF5F"

EPISODES_DIRNAME = "episodes"
REPORT_SUFFIX = ".report.json"

_BROKE_BEFORE_TURN = "before its model turn"
_PREVENTION_LINE = (
    "Prevention in this release: the runner re-execs before importing "
    "refreshed code, behind an import-firewall test."
)


def _episode_dedup_key(episode_id: str) -> str:
    """Return the upsert dedup key for one update episode."""
    return f"agent-auto-restart:{episode_id}"


def _episode_slug(episode_id: str) -> str:
    """Return the report filename stem for one episode id."""
    slug = "".join(
        ch if ch.isalnum() or ch in ("-", "_", ".", "@") else "_" for ch in episode_id
    ).strip("._")
    return (slug or "episode")[:80]


def _episode_report_path(episode_id: str) -> Path:
    """Return the live-report path for one episode id."""
    from sase.agent.auto_restart.ledger import auto_restart_root

    return (
        auto_restart_root()
        / EPISODES_DIRNAME
        / f"{_episode_slug(episode_id)}{REPORT_SUFFIX}"
    )


def _timestamp() -> str:
    from datetime import datetime

    from sase.core.time import get_timezone

    return datetime.now(get_timezone()).isoformat()


def _display_episode(episode_id: str) -> str:
    if len(episode_id) <= 32:
        return episode_id
    return episode_id[:12] + "…"


def _episode_records(episode_id: str) -> list[Any]:
    """Return ledger records carrying *episode_id*, newest claim first."""
    from sase.agent.auto_restart.ledger import iter_ledger_records

    try:
        records = iter_ledger_records()
    except Exception:
        return []
    return [r for r in records if getattr(r.record, "episode_id", None) == episode_id]


def _verdict_of(stored: Any) -> dict[str, Any]:
    extra = getattr(stored, "extra", None) or {}
    verdict = extra.get("python_verdict")
    return dict(verdict) if isinstance(verdict, dict) else {}


def _witnesses_of(stored: Any) -> dict[str, Any]:
    extra = getattr(stored, "extra", None) or {}
    witnesses = extra.get("python_witnesses")
    return dict(witnesses) if isinstance(witnesses, dict) else {}


def _record_state(stored: Any) -> str:
    return str(getattr(stored.record, "state", "") or "")


def _is_relaunched(stored: Any) -> bool:
    return _record_state(stored) in (
        "launching",
        "launched",
        "settled_ok",
        "settled_failed",
    )


def _is_in_flight(stored: Any) -> bool:
    return _record_state(stored) in ("claimed", "deferred", "launching")


def _signature_text(stored: Any) -> str:
    """Return the short human signature for one record (no fail/error lead)."""
    verdict = _verdict_of(stored)
    for key in ("signature", "family", "tier"):
        value = verdict.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:120]
    return "update-skew failure"


def _broke_during(stored: Any) -> str:
    """Return the phase phrase for one record's death."""
    witnesses = _witnesses_of(stored)
    if isinstance(witnesses.get("refresh_log_line"), dict):
        return "refreshing after %wait"
    phase = str(_verdict_of(stored).get("phase_class") or "")
    if phase == "post_provider":
        return "after its model turn"
    if phase == "plan_handoff":
        return "at a plan handoff"
    return _BROKE_BEFORE_TURN


def _update_ref(stored: Any) -> str:
    witnesses = _witnesses_of(stored)
    refresh = witnesses.get("refresh_log_line")
    if isinstance(refresh, dict):
        old = str(refresh.get("from") or "")[:12]
        new = str(refresh.get("to") or "")[:12]
        if old or new:
            return f"{old or '?'} → {new or '?'}"
    return ""


def _replacement_outcome(stored: Any) -> str:
    """Return the live Now-cell for one record: RUNNING, DONE, or FAILED."""
    launched_dir = getattr(stored.record, "launched_artifacts_dir", None)
    if not launched_dir:
        return "RUNNING" if _is_relaunched(stored) else "—"
    try:
        done = json.loads(
            (Path(str(launched_dir)) / "done.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return "RUNNING"
    if not isinstance(done, dict):
        return "RUNNING"
    outcome = str(done.get("outcome") or "")
    if outcome == "failed":
        return "FAILED"
    if outcome in ("completed", "success", "done"):
        return "DONE"
    return "RUNNING"


def _action_cell(stored: Any) -> str:
    if _is_relaunched(stored):
        return "relaunched"
    if _is_in_flight(stored):
        return "restarting"
    reason = str(getattr(stored.record, "decline_reason", "") or "left alone")
    return f"left alone — {reason}"[:80]


def _build_episode_report(
    episode_id: str, records: list[Any] | None = None
) -> dict[str, Any]:
    """Build the live ChopReport document for one episode.

    Only ``ok``/``warn``/``muted`` tones are used. Raises nothing: an empty
    episode still yields a valid document.
    """
    from sase.chops import ChopReport

    if records is None:
        records = _episode_records(episode_id)
    relaunched = [r for r in records if _is_relaunched(r)]
    left = [r for r in records if not _is_relaunched(r) and not _is_in_flight(r)]
    in_flight = [r for r in records if _is_in_flight(r)]
    display = _display_episode(episode_id)

    title = f"↻ Auto-restart report · {display}"
    report = ChopReport(title=title[:64])
    n_left = len(left)
    report.headline(
        f"{len(relaunched)} agent{'s' if len(relaunched) != 1 else ''} restarted · "
        f"{n_left} left alone",
        tone="ok" if not n_left and not in_flight else "warn",
    )

    kv: dict[str, str] = {}
    update_refs = sorted({_update_ref(r) for r in records if _update_ref(r)})
    if update_refs:
        kv["Update"] = update_refs[0]
    culprits = sorted(
        {
            str(w["file_proof"].get("culprit_commit", ""))[:12]
            for r in records
            for w in [_witnesses_of(r)]
            if isinstance(w.get("file_proof"), dict)
            and str(w["file_proof"].get("culprit_commit") or "")
        }
    )
    if culprits:
        kv["Culprit"] = culprits[0]
        subjects = sorted(
            {
                str(w["file_proof"].get("culprit_subject", "") or "").strip()
                for r in records
                for w in [_witnesses_of(r)]
                if isinstance(w.get("file_proof"), dict)
                and str(w["file_proof"].get("culprit_subject") or "").strip()
            }
        )
        subjects = [s for s in subjects if s]
        if subjects:
            kv["Culprit commit"] = subjects[0][:120]
    fired = sorted(
        {
            str(wit)
            for r in records
            for wit in (_verdict_of(r).get("witnesses_fired") or [])
            if str(wit).strip()
        }
    )
    if fired:
        kv["Witnesses"] = ", ".join(fired)[:160]
    if kv:
        report.kv(kv)

    rows = report.rows(
        columns=["Agent", "Project", "Broke during", "Signature", "Action", "Now"]
    )
    for stored in records:
        name = str(getattr(stored.record, "agent_name", "") or "?")
        project = str(getattr(stored.record, "project", "") or "?")
        rows.row(
            [
                name,
                project,
                _broke_during(stored),
                _signature_text(stored),
                _action_cell(stored),
                _replacement_outcome(stored),
            ],
            tone="ok" if _is_relaunched(stored) else "muted",
        )

    if left:
        report.bullets(
            [
                f"{getattr(r.record, 'agent_name', '?')} — "
                f"{getattr(r.record, 'decline_reason', 'left alone') or 'left alone'}"
                for r in left
            ],
            tone="muted",
        )

    if relaunched:
        report.text(
            "Why this happened: sase changed while these agents waited, so their "
            "in-memory code no longer matched the files on disk. Each lineage is "
            "relaunched at most once, under the same name.",
        )
    else:
        report.text(
            "Why this happened: sase changed while these agents waited, so their "
            "in-memory code no longer matched the files on disk. No lineage has "
            "been relaunched yet.",
        )
    report.divider()
    report.text(_PREVENTION_LINE, tone="muted")
    return report.to_dict()


def refresh_episode_report(episode_id: str) -> Path | None:
    """Re-render one episode's live report from its ledger records.

    Writes atomically under a file lock, validated with
    :func:`validate_chop_report`. Returns the path, or ``None`` when the
    episode has no ledger records yet or the write fails. Never raises:
    reporting must not break the healer.
    """
    from sase.notification_gates.durability import atomic_write_json, file_lock

    records = _episode_records(episode_id)
    if not records:
        return None
    try:
        document = _build_episode_report(episode_id, records)
        from sase.chops import validate_chop_report

        validated = validate_chop_report(document)
    except Exception:
        return None
    path = _episode_report_path(episode_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with file_lock(path.with_suffix(".lock"), timeout=10.0):
                atomic_write_json(path, validated)
        except Exception:
            atomic_write_json(path, validated)
    except OSError:
        return None
    return path


def _episode_notes(episode_id: str, records: list[Any]) -> list[str]:
    """Build the episode row notes honoring the copy rules.

    ``notes[0]`` is the calm title (never "fail"/"error"); exception text
    appears only in note 2 or later.
    """
    display = _display_episode(episode_id)
    relaunched = [r for r in records if _is_relaunched(r)]
    count = len(relaunched)
    if count == 1:
        name = str(getattr(relaunched[0].record, "agent_name", "") or "1 agent")
        title = f"↻ Restarted {name} after sase update {display}"
        lowered = title.lower()
        if "fail" in lowered or "error" in lowered:
            title = f"↻ Restarted 1 agent after sase update {display}"
        notes = [title]
    else:
        notes = [f"↻ Restarted {count} agents after sase update {display}"]

    symbols = sorted(
        {
            str(w["file_proof"].get("symbol", ""))
            for r in records
            for w in [_witnesses_of(r)]
            if isinstance(w.get("file_proof"), dict)
            and str(w["file_proof"].get("symbol") or "")
        }
    )
    if symbols:
        notes.append(
            "sase changed while they waited: their in-memory code asked the new "
            f"files for {symbols[0]}, which no longer matched what they imported."
        )
    else:
        notes.append(
            "sase changed while they waited, and the new code no longer matched "
            "what they had imported."
        )

    by_project: dict[str, list[str]] = {}
    for stored in relaunched:
        project = str(getattr(stored.record, "project", "") or "sase")
        name = str(getattr(stored.record, "agent_name", "") or "?")
        by_project.setdefault(project, []).append(f"{name} · {_signature_text(stored)}")
    for project in sorted(by_project):
        names = ", ".join(sorted(by_project[project]))
        notes.append(f"• {names} ({project}) — relaunched under the same names")

    pre_provider = all(
        str(_verdict_of(r).get("phase_class") or "") == "pre_provider"
        for r in relaunched
    )
    if relaunched and pre_provider:
        refreshed = any(
            isinstance(_witnesses_of(r).get("refresh_log_line"), dict)
            for r in relaunched
        )
        if refreshed:
            notes.append(
                f"Nothing was lost: all {count} broke while refreshing after "
                "%wait, before their model turn."
            )
        else:
            notes.append(
                f"Nothing was lost: all {count} broke before their model turn."
            )
    notes.append(
        "Each agent gets one automatic restart. If one breaks again you will "
        "get a normal failure notice and sase will not retry it."
    )
    return notes


def _episode_tags(records: list[Any]) -> list[str]:
    from sase.notifications.models import normalize_notification_tags

    tiers = sorted(
        {
            str(_verdict_of(r).get("tier") or "")
            for r in records
            if str(_verdict_of(r).get("tier") or "")
        }
    )
    tier_tag = tiers[0] if tiers else "update-skew"
    return normalize_notification_tags(["sase-update", "auto-restart", tier_tag])


def _episode_evidence_files(records: list[Any]) -> list[str]:
    """Collect preserved evidence paths for one episode's records."""
    files: list[str] = []
    for stored in records:
        evidence = getattr(stored.record, "evidence_dir", None)
        if evidence and str(evidence) not in files:
            files.append(str(evidence))
            report = Path(str(evidence)) / "error_report.md"
            try:
                if report.is_file() and str(report) not in files:
                    files.insert(len(files) - 1, str(report))
            except OSError:
                pass
    return files[:20]


def _resolve_dedup_key(episode_id: str) -> str:
    """Return the live dedup key, rolling over dismissed episodes.

    When the episode row (or its latest ``#N`` continuation) was dismissed,
    the next restart opens a new ``<episode>#N`` row instead of reviving the
    dismissed one. A restart is never invisible.
    """
    from sase.notifications.store import load_notifications

    base = _episode_dedup_key(episode_id)
    try:
        rows = load_notifications(include_dismissed=True)
    except Exception:
        return base
    owned = [
        r for r in rows if r.sender == SENDER and (r.dedup_key or "").startswith(base)
    ]
    if not owned:
        return base

    def _suffix(key: str) -> int:
        rest = key[len(base) :]
        if not rest:
            return 1
        if rest.startswith("#") and rest[1:].isdigit():
            return int(rest[1:])
        return 0

    numbered = [(_suffix(r.dedup_key or ""), r) for r in owned]
    numbered = [(n, r) for n, r in numbered if n > 0]
    if not numbered:
        return base
    top_n, top_row = max(numbered, key=lambda item: item[0])
    if not top_row.dismissed:
        return top_row.dedup_key or base
    return f"{base}#{top_n + 1}"


def _refresh_row_content(dedup_key: str, episode_id: str) -> None:
    """Refresh the episode row's notes and inline snapshot in place.

    Uses the reconcile path, which leaves delivery cursors untouched, so
    the refresh never re-toasts or re-pushes.
    """
    from sase.notifications.models import Notification
    from sase.notifications.store import load_notifications, reconcile_notification_rows

    try:
        rows = load_notifications(include_dismissed=True)
    except Exception:
        return
    current = next(
        (r for r in rows if r.sender == SENDER and r.dedup_key == dedup_key),
        None,
    )
    if current is None or current.dismissed:
        return
    records = _episode_records(episode_id)
    notes = _episode_notes(episode_id, records)
    action_data = dict(current.action_data)
    path = _episode_report_path(episode_id)
    action_data["report_path"] = str(path)
    action_data["report_title"] = notes[0][:64]
    try:
        snapshot = _build_episode_report(episode_id, records)
        action_data["report"] = json.dumps(snapshot)
    except Exception:
        pass
    refreshed = Notification(
        id=current.id,
        timestamp=current.timestamp,
        sender=current.sender,
        icon=current.icon,
        color=current.color,
        notes=notes,
        files=list(current.files),
        tags=list(current.tags),
        action=current.action,
        action_data=action_data,
        read=current.read,
        dismissed=current.dismissed,
        silent=current.silent,
        muted=current.muted,
        snooze_until=current.snooze_until,
        resurfaced_at=current.resurfaced_at,
        plus_ones=list(current.plus_ones),
        plus_ones_dropped=current.plus_ones_dropped,
        dedup_key=current.dedup_key,
    )
    try:
        reconcile_notification_rows([refreshed])
    except Exception:
        pass


def _guarded_upsert(notification: Any, *, plus_one_note: str) -> Any:
    """Upsert one notification; skip silently when the store is unavailable."""
    from sase.core.state_write_guard import best_effort_test_state_write_allowed
    from sase.notifications.store import notifications_file_path, upsert_notification

    try:
        path = notifications_file_path()
    except Exception:
        return None
    try:
        if not best_effort_test_state_write_allowed(
            path, category="auto-restart-notifications"
        ):
            return None
    except Exception:
        pass
    try:
        return upsert_notification(
            notification,
            plus_one_note=plus_one_note,
            plus_one_timestamp=notification.timestamp,
        )
    except Exception:
        return None


def publish_relaunch(
    *,
    episode_id: str,
    agent_name: str,
    update_ref: str,
    reason_text: str,
    evidence_files: list[str] | None = None,
) -> Any:
    """Upsert the episode row for one relaunch (plus-one within it).

    The first relaunch in an episode creates the row (and its single
    information toast); later relaunches append one ``+1`` note each and
    refresh the title, notes, and inline report snapshot in place without
    moving delivery cursors.
    """
    from sase.notifications.models import Notification

    ref = update_ref or _display_episode(episode_id)
    dedup_key = _resolve_dedup_key(episode_id)
    records = _episode_records(episode_id)
    notes = (
        _episode_notes(episode_id, records)
        if records
        else [f"↻ Restarted {agent_name} after sase update {ref}"]
    )
    files = list(evidence_files or []) or _episode_evidence_files(records)
    path = _episode_report_path(episode_id)
    action_data = {"report_path": str(path), "report_title": notes[0][:64]}
    notification = Notification(
        id=str(uuid4()),
        timestamp=_timestamp(),
        sender=SENDER,
        icon=ICON,
        color=COLOR,
        notes=notes,
        files=files,
        tags=_episode_tags(records),
        action="ViewReport",
        action_data=action_data,
        dedup_key=dedup_key,
    )
    outcome = _guarded_upsert(notification, plus_one_note=f"Restarted {agent_name}")
    try:
        refresh_episode_report(episode_id)
    except Exception:
        pass
    try:
        _refresh_row_content(dedup_key, episode_id)
    except Exception:
        pass
    return outcome


def publish_escalation(
    *,
    agent_name: str,
    title: str,
    detail: str,
    episode_id: str | None = None,
    kind: str = "decline",
    artifacts_dir: str | None = None,
) -> Any:
    """Post one loud error-severity escalation.

    ``kind="storm"`` posts as ``agent.auto-restart`` with ``ViewErrorReport``
    so it lands in the Errors bucket at error severity. Every other kind
    re-surfaces the agent's own failure notification (``sender=user-agent``)
    with the escalation sentence appended, per the escalation spec. Callers
    may still pass an explicit title/detail; storm copy is built here so all
    storm rows read identically.
    """
    if kind != "storm":
        return resurface_failure(
            agent_name=agent_name,
            reason_text=f"{title} {detail}".strip(),
            artifacts_dir=artifacts_dir,
        )
    from sase.notifications.models import Notification, normalize_notification_tags

    storm_title = title or (
        f"Auto-restart paused: agents kept breaking during episode "
        f"{_display_episode(episode_id or 'unknown')} — this looks like a real "
        "bug, not an update race."
    )
    notes = [storm_title]
    if detail:
        notes.append(detail)
    notification = Notification(
        id=str(uuid4()),
        timestamp=_timestamp(),
        sender=SENDER,
        icon=ICON,
        color=COLOR,
        notes=notes,
        tags=normalize_notification_tags(["sase-update", "auto-restart", "error"]),
        action="ViewErrorReport",
        dedup_key=(
            f"{_episode_dedup_key(episode_id)}:{agent_name}:storm"
            if episode_id
            else f"agent-auto-restart:{agent_name}:storm"
        ),
    )
    outcome = _guarded_upsert(notification, plus_one_note=storm_title)
    if episode_id:
        try:
            refresh_episode_report(episode_id)
        except Exception:
            pass
    return outcome


def resurface_failure(
    *,
    agent_name: str,
    reason_text: str,
    artifacts_dir: str | None = None,
) -> Any:
    """Make the original failure visible again with one explanatory note.

    Rebuilds the standard failure notification (``sender=user-agent``,
    ``ViewErrorReport``, Errors bucket) from ``done.json`` and
    ``error_report.md`` when the row is missing; never swallows the failure.
    """
    from sase.notifications.models import Notification, normalize_notification_tags

    notes = [f"{agent_name} failed and was not restarted automatically."]
    if reason_text:
        notes.append(reason_text)
    files: list[str] = []
    if artifacts_dir:
        report = Path(artifacts_dir) / "error_report.md"
        try:
            if report.is_file():
                files.append(str(report))
        except OSError:
            pass
    notification = Notification(
        id=str(uuid4()),
        timestamp=_timestamp(),
        sender="user-agent",
        notes=notes,
        files=files,
        tags=normalize_notification_tags(["auto-restart", "resurfaced"]),
        action="ViewErrorReport",
        dedup_key=f"agent-auto-restart-resurfaced:{agent_name}",
    )
    return _guarded_upsert(
        notification, plus_one_note=f"{agent_name} still needs attention"
    )


__all__ = [
    "COLOR",
    "EPISODES_DIRNAME",
    "ICON",
    "REPORT_SUFFIX",
    "SENDER",
    "publish_escalation",
    "publish_relaunch",
    "refresh_episode_report",
    "resurface_failure",
]
