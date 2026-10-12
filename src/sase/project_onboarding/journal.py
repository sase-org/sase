"""Atomic ownership journals for project onboarding."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any

from sase.core.atomic_temp import reap_stale_atomic_temps
from sase.core.paths import sase_home

_JOURNAL_SCHEMA_VERSION = 1
_JOURNAL_RUNNING = "running"
_JOURNAL_FAILED = "failed"
_JOURNAL_COMPLETE = "complete"
_LIVE_JOURNAL_STATUSES = frozenset({_JOURNAL_RUNNING, _JOURNAL_FAILED})
_JOURNALS_DIRNAME = "journals"
_RETENTION_DAYS = 30
_JOURNAL_FILE_MODE = 0o600

_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def journals_dir() -> Path:
    """Return the ownership-journal directory under ``$SASE_HOME``."""

    return sase_home() / "project_onboarding" / _JOURNALS_DIRNAME


def journal_path(identity_key: str, display: str = "") -> Path:
    """Return the canonical journal path for *identity_key*."""

    stem = _display_stem(display or identity_key)
    digest = hashlib.sha1(identity_key.encode("utf-8")).hexdigest()[:12]
    return journals_dir() / f"{stem}-{digest}.json"


def journal_lock_path(identity_key: str) -> Path:
    """Return the cooperating lock path for *identity_key*."""

    digest = hashlib.sha1(identity_key.encode("utf-8")).hexdigest()[:12]
    return journals_dir() / f".{digest}.lock"


@contextmanager
def journal_lock(identity_key: str, display: str = "") -> Iterator[Path]:
    """Hold an exclusive flock on the journal for *identity_key*."""

    path = journal_path(identity_key, display)
    lock_path = journal_lock_path(identity_key)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield path
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def list_incomplete() -> list[dict[str, Any]]:
    """Return live (running/failed) journals in the discovery wire shape."""

    journals: list[dict[str, Any]] = []
    for raw in _iter_raw_journals():
        status = str(raw.get("status") or "")
        identity_key = str(raw.get("identity_key") or "")
        if status not in _LIVE_JOURNAL_STATUSES or not identity_key:
            continue
        ref = str(raw.get("ref") or "")
        journals.append(
            {
                "identity_key": identity_key,
                "ref": ref,
                "display": str(raw.get("display") or ref),
                "status": status,
                "stopped_at": str(raw.get("stopped_at") or ""),
                "updated_at": str(raw.get("updated_at") or ""),
            }
        )
    return journals


def lookup_journal(identity_key: str) -> dict[str, Any] | None:
    """Return the stored journal for *identity_key*, tolerating damage."""

    found = _lookup_entry(identity_key)
    return None if found is None else found[1]


def _lookup_entry(identity_key: str) -> tuple[Path, dict[str, Any]] | None:
    wanted = identity_key.casefold()
    if not wanted:
        return None
    try:
        paths = sorted(journals_dir().glob("*.json"), key=lambda item: item.name)
    except OSError:
        return None
    for path in paths:
        raw = _load_raw(path)
        if raw is not None and str(raw.get("identity_key") or "").casefold() == wanted:
            return path, raw
    return None


def ownership_facts(
    identity_key: str,
    fingerprint: str,
    *,
    current_config_hash: str = "",
) -> dict[str, Any] | None:
    """Return planner journal facts when identity and fingerprint both match."""

    raw = lookup_journal(identity_key)
    if raw is None:
        return None
    stored = str(raw.get("intent_fingerprint") or "")
    if not fingerprint or stored != fingerprint:
        return None
    if str(raw.get("identity_key") or "").casefold() != identity_key.casefold():
        return None
    remote = raw.get("remote")
    remote_map = remote if isinstance(remote, dict) else {}
    facts: dict[str, Any] = {
        "intent_recorded_at": str(raw.get("intent_recorded_at") or ""),
        "remote_created": bool(remote_map.get("created")),
        "repo_id": str(remote_map.get("repo_id") or ""),
    }
    if str(raw.get("status") or "") not in _LIVE_JOURNAL_STATUSES:
        facts["management_incomplete"] = False
        facts["config_changes_owned"] = False
        return facts

    management = raw.get("management")
    management_map = management if isinstance(management, dict) else {}
    setup_required = raw.get("setup_required")
    if isinstance(setup_required, bool):
        facts["setup_required"] = setup_required
    push_verified = bool(
        management_map.get("push_verified") or management_map.get("pushed")
    )
    facts["management_incomplete"] = bool(setup_required is True and not push_verified)
    baseline_hash = str(management_map.get("baseline_config_hash") or "")
    expected_hash = str(management_map.get("expected_config_hash") or "")
    current_hash = current_config_hash
    marker_stage = str(management_map.get("marker_write_stage") or "")
    facts["config_changes_owned"] = bool(
        facts["management_incomplete"]
        and expected_hash
        and expected_hash != baseline_hash
        and current_hash == expected_hash
        and marker_stage in {"write_started", "written"}
    )
    return facts


def record_intent(
    *,
    identity_key: str,
    ref: str,
    display: str,
    workflow_type: str,
    mode: str,
    intent_fingerprint: str,
    proc_id: str = "",
    project_key: str = "",
    setup_required: bool | None = None,
) -> dict[str, Any]:
    """Write or refresh the active intent before any onboarding effect."""

    now = _utc_now()
    with journal_lock(identity_key, display) as path:
        found = _lookup_entry(identity_key)
        current = found[1] if found is not None else {}
        if found is not None:
            path = found[0]
        same_intent = bool(
            found is not None
            and str(current.get("status") or "") in _LIVE_JOURNAL_STATUSES
            and str(current.get("identity_key") or "").casefold()
            == identity_key.casefold()
            and str(current.get("intent_fingerprint") or "") == intent_fingerprint
        )
        record = _blank_record(
            identity_key=identity_key,
            ref=ref,
            display=display,
            workflow_type=workflow_type,
            mode=mode,
            intent_fingerprint=intent_fingerprint,
            now=now,
        )
        if same_intent:
            record["remote"] = _merge_mapping(current.get("remote"), record["remote"])
            record["steps"] = _merge_mapping(current.get("steps"), record["steps"])
            record["management"] = _merge_mapping(
                current.get("management"), record["management"]
            )
            if isinstance(current.get("setup_required"), bool):
                record["setup_required"] = current["setup_required"]
        if record.get("setup_required") is None and setup_required is not None:
            record["setup_required"] = setup_required
        if proc_id:
            record["proc_id"] = proc_id
        elif current.get("proc_id"):
            record["proc_id"] = str(current["proc_id"])
        if project_key:
            record["project_key"] = project_key
        elif current.get("project_key"):
            record["project_key"] = str(current["project_key"])
        _write_record(path, record, now=now)
        return record


def update_management(
    identity_key: str,
    intent_fingerprint: str,
    *,
    display: str = "",
    **updates: Any,
) -> dict[str, Any]:
    """Atomically persist management recovery evidence for a matching intent."""

    now = _utc_now()
    with journal_lock(identity_key, display) as path:
        found = _lookup_entry(identity_key)
        if found is None:
            raise ValueError("onboarding intent journal is missing")
        path, record = found
        if str(record.get("intent_fingerprint") or "") != intent_fingerprint:
            raise ValueError("onboarding intent journal fingerprint changed")
        if str(record.get("status") or "") not in _LIVE_JOURNAL_STATUSES:
            raise ValueError("onboarding intent journal is not active")
        management = record.get("management")
        management_map = dict(management) if isinstance(management, dict) else {}
        management_map.update(updates)
        record["management"] = management_map
        record["updated_at"] = now
        _write_record(path, record, now=now)
        return record


def update_step(
    identity_key: str,
    step_id: str,
    *,
    status: str,
    message: str = "",
    display: str = "",
    finished: bool | None = None,
) -> dict[str, Any]:
    """Atomically record one step's status, timestamp, and message."""

    now = _utc_now()
    display_name = display
    with journal_lock(identity_key, display_name) as path:
        found = _lookup_entry(identity_key)
        if found is None:
            record = _blank_record(
                identity_key=identity_key,
                ref="",
                display=display_name,
                workflow_type="",
                mode="",
                intent_fingerprint="",
                now=now,
            )
        else:
            path, record = found
        steps = record.get("steps")
        if not isinstance(steps, dict):
            steps = {}
        entry = (
            dict(steps.get(step_id) or {})
            if isinstance(steps.get(step_id), dict)
            else {}
        )
        entry["status"] = status
        entry["updated_at"] = now
        is_finished = (
            finished
            if finished is not None
            else status
            in {
                "done",
                "failed",
            }
        )
        if is_finished:
            entry["finished_at"] = now
        if message:
            entry["message"] = message
        steps[step_id] = entry
        record["steps"] = steps
        if status == "failed":
            record["status"] = _JOURNAL_FAILED
            record["stopped_at"] = now
            record["stopped_step"] = step_id
        record["updated_at"] = now
        _write_record(path, record, now=now)
        return record


def set_journal_status(
    identity_key: str,
    status: str,
    *,
    display: str = "",
    project_key: str = "",
    message: str = "",
) -> dict[str, Any]:
    """Set the journal's overall running/failed/complete status."""

    now = _utc_now()
    with journal_lock(identity_key, display) as path:
        found = _lookup_entry(identity_key)
        if found is None:
            record = _blank_record(
                identity_key=identity_key,
                ref="",
                display=display or identity_key,
                workflow_type="",
                mode="",
                intent_fingerprint="",
                now=now,
            )
        else:
            path, record = found
        record["status"] = status
        record["updated_at"] = now
        if status in {_JOURNAL_FAILED, _JOURNAL_COMPLETE}:
            record["stopped_at"] = now
        if project_key:
            record["project_key"] = project_key
        if message:
            record["message"] = message
        _write_record(path, record, now=now)
        return record


def _blank_record(
    *,
    identity_key: str,
    ref: str,
    display: str,
    workflow_type: str,
    mode: str,
    intent_fingerprint: str,
    now: str,
) -> dict[str, Any]:
    return {
        "schema_version": _JOURNAL_SCHEMA_VERSION,
        "identity_key": identity_key,
        "ref": ref,
        "display": display or ref or identity_key,
        "workflow_type": workflow_type,
        "mode": mode,
        "intent_fingerprint": intent_fingerprint,
        "status": _JOURNAL_RUNNING,
        "setup_required": None,
        "intent_recorded_at": now,
        "updated_at": now,
        "remote": {"created": False, "repo_id": "", "created_at": ""},
        "steps": {},
        "management": {
            "stage": "",
            "marker_written": False,
            "baseline_config_hash": "",
            "expected_config_hash": "",
            "current_config_hash": "",
            "marker_write_stage": "",
            "commit_id": "",
            "commit_parent": "",
            "commit_content_hash": "",
            "commit_message": "",
            "push_expected_oid": "",
            "push_verified": False,
            "pushed": False,
        },
        "stopped_at": "",
        "stopped_step": "",
        "proc_id": "",
        "project_key": "",
    }


def _write_record(path: Path, record: Mapping[str, Any], *, now: str) -> None:
    payload = dict(record)
    payload.setdefault("schema_version", _JOURNAL_SCHEMA_VERSION)
    payload["updated_at"] = str(payload.get("updated_at") or now)
    path.parent.mkdir(parents=True, exist_ok=True)
    reap_stale_atomic_temps(path)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    encoded = json.dumps(payload, indent=2, sort_keys=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(tmp_path, flags, _JOURNAL_FILE_MODE)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        os.chmod(path, _JOURNAL_FILE_MODE)
    except OSError:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise
    _prune_complete(_parse_utc(now) or datetime.now(UTC))


def _prune_complete(now: datetime) -> None:
    cutoff = now - timedelta(days=_RETENTION_DAYS)
    try:
        paths = list(journals_dir().glob("*.json"))
    except OSError:
        return
    for path in paths:
        raw = _load_raw(path)
        if raw is None:
            continue
        if str(raw.get("status") or "") != _JOURNAL_COMPLETE:
            continue
        stamp = _parse_utc(
            str(raw.get("updated_at") or raw.get("intent_recorded_at") or "")
        )
        if stamp is None or stamp > cutoff:
            continue
        try:
            path.unlink()
        except OSError:
            continue


def _iter_raw_journals() -> Iterator[dict[str, Any]]:
    try:
        paths = sorted(journals_dir().glob("*.json"), key=lambda item: item.name)
    except OSError:
        return
    for path in paths:
        raw = _load_raw(path)
        if raw is not None:
            yield raw


def _load_raw(path: Path) -> dict[str, Any] | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _display_stem(display: str) -> str:
    stem = _UNSAFE_RE.sub("-", display.strip()).strip("-._")
    return (stem or "journal")[:80]


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _merge_mapping(existing: Any, default: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(default)
    if isinstance(existing, dict):
        merged.update(existing)
    return merged


__all__ = [
    "journal_lock",
    "journal_lock_path",
    "journal_path",
    "journals_dir",
    "list_incomplete",
    "lookup_journal",
    "ownership_facts",
    "record_intent",
    "set_journal_status",
    "update_management",
    "update_step",
]
