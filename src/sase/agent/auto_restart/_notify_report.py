"""Episode report rendering and live report refresh for auto-restart."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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


def _episode_slug(episode_id: str) -> str:
    """Return the report filename stem for one episode id."""
    slug = "".join(
        ch if ch.isalnum() or ch in ("-", "_", ".", "@") else "_" for ch in episode_id
    ).strip("._")
    return (slug or "episode")[:80]


def episode_report_path(episode_id: str) -> Path:
    """Return the live-report path for one episode id."""
    from sase.agent.auto_restart.ledger import auto_restart_root

    return (
        auto_restart_root()
        / EPISODES_DIRNAME
        / f"{_episode_slug(episode_id)}{REPORT_SUFFIX}"
    )


def display_episode(episode_id: str) -> str:
    if len(episode_id) <= 32:
        return episode_id
    return episode_id[:12] + "…"


def episode_records(episode_id: str) -> list[Any]:
    """Return ledger records carrying *episode_id*, newest claim first."""
    from sase.agent.auto_restart.ledger import iter_ledger_records

    try:
        records = iter_ledger_records()
    except Exception:
        return []
    return [r for r in records if getattr(r.record, "episode_id", None) == episode_id]


def verdict_of(stored: Any) -> dict[str, Any]:
    extra = getattr(stored, "extra", None) or {}
    verdict = extra.get("python_verdict")
    return dict(verdict) if isinstance(verdict, dict) else {}


def witnesses_of(stored: Any) -> dict[str, Any]:
    extra = getattr(stored, "extra", None) or {}
    witnesses = extra.get("python_witnesses")
    return dict(witnesses) if isinstance(witnesses, dict) else {}


def _record_state(stored: Any) -> str:
    return str(getattr(stored.record, "state", "") or "")


def is_relaunched(stored: Any) -> bool:
    return _record_state(stored) in (
        "launching",
        "launched",
        "settled_ok",
        "settled_failed",
    )


def _is_in_flight(stored: Any) -> bool:
    return _record_state(stored) in ("claimed", "deferred", "launching")


def signature_text(stored: Any) -> str:
    """Return the short human signature for one record (no fail/error lead)."""
    verdict = verdict_of(stored)
    for key in ("signature", "family", "tier"):
        value = verdict.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:120]
    return "update-skew failure"


def _broke_during(stored: Any) -> str:
    """Return the phase phrase for one record's death."""
    witnesses = witnesses_of(stored)
    if isinstance(witnesses.get("refresh_log_line"), dict):
        return "refreshing after %wait"
    phase = str(verdict_of(stored).get("phase_class") or "")
    if phase == "post_provider":
        return "after its model turn"
    if phase == "plan_handoff":
        return "at a plan handoff"
    return _BROKE_BEFORE_TURN


def _update_ref(stored: Any) -> str:
    witnesses = witnesses_of(stored)
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
        return "RUNNING" if is_relaunched(stored) else "—"
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
    if is_relaunched(stored):
        return "relaunched"
    if _is_in_flight(stored):
        return "restarting"
    reason = str(getattr(stored.record, "decline_reason", "") or "left alone")
    return f"left alone — {reason}"[:80]


def build_episode_report(
    episode_id: str, records: list[Any] | None = None
) -> dict[str, Any]:
    """Build the live ChopReport document for one episode.

    Only ``ok``/``warn``/``muted`` tones are used. Raises nothing: an empty
    episode still yields a valid document.
    """
    from sase.chops import ChopReport

    if records is None:
        records = episode_records(episode_id)
    relaunched = [r for r in records if is_relaunched(r)]
    left = [r for r in records if not is_relaunched(r) and not _is_in_flight(r)]
    in_flight = [r for r in records if _is_in_flight(r)]
    display = display_episode(episode_id)

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
            for w in [witnesses_of(r)]
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
                for w in [witnesses_of(r)]
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
            for wit in (verdict_of(r).get("witnesses_fired") or [])
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
                signature_text(stored),
                _action_cell(stored),
                _replacement_outcome(stored),
            ],
            tone="ok" if is_relaunched(stored) else "muted",
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

    records = episode_records(episode_id)
    if not records:
        return None
    try:
        document = build_episode_report(episode_id, records)
        from sase.chops import validate_chop_report

        validated = validate_chop_report(document)
    except Exception:
        return None
    path = episode_report_path(episode_id)
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
