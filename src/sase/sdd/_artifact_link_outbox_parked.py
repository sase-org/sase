"""Replayable parked ledger for artifact-link operations that cannot converge."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
import fcntl
import json
import os
from pathlib import Path
import time
from typing import Any

from sase.core.paths import sase_projects_dir, validate_sase_project_name
from sase.memory.locks import locked_file
from sase.sdd._artifact_link_outbox_types import (
    ARTIFACT_LINK_OUTBOX_PARKED_FILENAME,
    ArtifactLinkOutboxEntry,
    entry_from_line,
    rows_from_events,
)

PARKED_RECHECK_SECONDS = 24 * 60 * 60

_PARKED_REASON_KEYS = ("foreign", "removed", "absent")


@dataclass(frozen=True, slots=True)
class ArtifactLinkParkedEntry:
    """One parked outbox operation plus the typed reasons that parked it."""

    entry: ArtifactLinkOutboxEntry
    parked_at: float
    last_checked_at: float
    reasons: tuple[str, ...]
    endpoints: tuple[dict[str, Any], ...] = ()

    def to_json_dict(self) -> dict[str, Any]:
        payload = self.entry.to_json_dict()
        payload["parked_at"] = self.parked_at
        payload["last_checked_at"] = self.last_checked_at
        payload["reasons"] = list(self.reasons)
        payload["endpoints"] = [dict(item) for item in self.endpoints]
        return payload

    def link_keys(self) -> tuple[tuple[str, str, str], ...]:
        if self.entry.row is not None:
            return (
                (
                    str(self.entry.row.get("source_ref") or ""),
                    str(self.entry.row.get("relation") or ""),
                    str(self.entry.row.get("target_ref") or ""),
                ),
            )
        if self.entry.event is None:
            return ()
        return tuple(
            (
                str(row.get("source_ref") or ""),
                str(row.get("relation") or ""),
                str(row.get("target_ref") or ""),
            )
            for row in rows_from_events((self.entry.event,))
        )


@dataclass(frozen=True, slots=True)
class _ArtifactLinkParkedStats:
    """Doctor-facing parked-ledger counts."""

    parked: int = 0
    parked_by_reason: tuple[tuple[str, int], ...] = ()


def artifact_link_outbox_parked_path(project_key: str) -> Path:
    """Return ``~/.sase/projects/<key>/artifact-link-outbox-parked.jsonl``."""

    validate_sase_project_name(project_key)
    return sase_projects_dir() / project_key / ARTIFACT_LINK_OUTBOX_PARKED_FILENAME


def read_artifact_link_parked_entries(
    project_key: str,
) -> tuple[ArtifactLinkParkedEntry, ...]:
    """Read valid parked ledger entries, skipping malformed JSONL rows."""

    path = artifact_link_outbox_parked_path(project_key)
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_SH):
        return _read_parked_entries_unlocked(path, project_key)


def find_parked_outbox_entry(
    project_key: str,
    operation_id: str,
) -> ArtifactLinkParkedEntry | None:
    """Return the parked entry for *operation_id*, if one exists."""

    token = f'"{operation_id}"'
    path = artifact_link_outbox_parked_path(project_key)
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_SH):
        if not path.is_file():
            return None
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        for line in lines:
            if token not in line or not line.strip():
                continue
            parsed = _parked_entry_from_line(line, project_key)
            if parsed is not None and parsed.entry.id == operation_id:
                return parsed
    return None


def inspect_artifact_link_parked(project_key: str) -> _ArtifactLinkParkedStats:
    """Return parked counts grouped by typed endpoint reason."""

    entries = read_artifact_link_parked_entries(project_key)
    counts: Counter[str] = Counter()
    for item in entries:
        for reason in _reason_keys_for(item):
            counts[reason] += 1
    return _ArtifactLinkParkedStats(
        parked=len(entries),
        parked_by_reason=tuple(sorted(counts.items())),
    )


def parked_artifact_link_keys(project_key: str) -> frozenset[tuple[str, str, str]]:
    """Return source/relation/target keys currently on the parked ledger."""

    keys: set[tuple[str, str, str]] = set()
    for item in read_artifact_link_parked_entries(project_key):
        keys.update(item.link_keys())
    return frozenset(keys)


def append_artifact_link_parked_entries(
    project_key: str,
    entries: Sequence[ArtifactLinkParkedEntry],
) -> int:
    """Append newly parked operations, skipping ids already on the ledger.

    Returns the number of records actually written.
    """

    if not entries:
        return 0
    path = artifact_link_outbox_parked_path(project_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
        existing_ids = {
            item.entry.id for item in _read_parked_entries_unlocked(path, project_key)
        }
        new_entries = [item for item in entries if item.entry.id not in existing_ids]
        if not new_entries:
            return 0
        with path.open("a", encoding="utf-8") as output_file:
            for item in new_entries:
                json.dump(item.to_json_dict(), output_file, sort_keys=True)
                output_file.write("\n")
                written += 1
            output_file.flush()
            os.fsync(output_file.fileno())
    return written


def rewrite_artifact_link_parked_entries(
    project_key: str,
    entries: Iterable[ArtifactLinkParkedEntry],
) -> None:
    """Replace the parked ledger with *entries*."""

    path = artifact_link_outbox_parked_path(project_key)
    lines = [json.dumps(item.to_json_dict(), sort_keys=True) for item in entries]
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
        _write_parked_lines(path, lines)


def parked_entry_from_outbox(
    entry: ArtifactLinkOutboxEntry,
    *,
    reasons: Sequence[str],
    endpoints: Sequence[Mapping[str, Any]] = (),
    now: float | None = None,
) -> ArtifactLinkParkedEntry:
    """Build a parked ledger record from an active outbox entry."""

    parked_at = float(time.time() if now is None else now)
    return ArtifactLinkParkedEntry(
        entry=entry,
        parked_at=parked_at,
        last_checked_at=parked_at,
        reasons=tuple(str(reason) for reason in reasons if str(reason)),
        endpoints=tuple(dict(item) for item in endpoints),
    )


def touch_parked_checked_at(
    item: ArtifactLinkParkedEntry,
    *,
    now: float,
) -> ArtifactLinkParkedEntry:
    """Return *item* with an updated last-checked timestamp."""

    return replace(item, last_checked_at=float(now))


def _read_parked_entries_unlocked(
    path: Path,
    project_key: str,
) -> tuple[ArtifactLinkParkedEntry, ...]:
    if not path.is_file():
        return ()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    entries: list[ArtifactLinkParkedEntry] = []
    seen: set[str] = set()
    for line in lines:
        if not line.strip():
            continue
        parsed = _parked_entry_from_line(line, project_key)
        if parsed is None or parsed.entry.id in seen:
            continue
        seen.add(parsed.entry.id)
        entries.append(parsed)
    return tuple(entries)


def _parked_entry_from_line(
    line: str,
    project_key: str,
) -> ArtifactLinkParkedEntry | None:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    parked_at = payload.pop("parked_at", None)
    last_checked_at = payload.pop("last_checked_at", parked_at)
    reasons = payload.pop("reasons", ())
    endpoints = payload.pop("endpoints", ())
    if not isinstance(parked_at, (int, float)) or isinstance(parked_at, bool):
        return None
    if not isinstance(last_checked_at, (int, float)) or isinstance(
        last_checked_at, bool
    ):
        last_checked_at = parked_at
    entry = entry_from_line(json.dumps(payload, sort_keys=True), project_key)
    if entry is None:
        return None
    parsed_reasons = (
        tuple(str(item) for item in reasons if str(item))
        if isinstance(reasons, list)
        else ()
    )
    parsed_endpoints = (
        tuple(dict(item) for item in endpoints if isinstance(item, dict))
        if isinstance(endpoints, list)
        else ()
    )
    return ArtifactLinkParkedEntry(
        entry=entry,
        parked_at=float(parked_at),
        last_checked_at=float(last_checked_at),
        reasons=parsed_reasons,
        endpoints=parsed_endpoints,
    )


def _reason_keys_for(item: ArtifactLinkParkedEntry) -> tuple[str, ...]:
    kinds: list[str] = []
    for endpoint in item.endpoints:
        kind = _outcome_kind(endpoint.get("outcome"))
        if kind in _PARKED_REASON_KEYS and kind not in kinds:
            kinds.append(kind)
    if kinds:
        return tuple(kinds)
    for reason in item.reasons:
        lowered = reason.casefold()
        for key in _PARKED_REASON_KEYS:
            token = f"outcome {key}"
            if token in lowered and key not in kinds:
                kinds.append(key)
    return tuple(kinds) if kinds else (("other",) if item.reasons else ())


def _outcome_kind(outcome: object) -> str:
    if isinstance(outcome, str):
        return outcome
    if isinstance(outcome, Mapping) and outcome:
        return str(next(iter(outcome)))
    return "other"


def _write_parked_lines(path: Path, lines: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as output_file:
            for line in lines:
                output_file.write(line)
                output_file.write("\n")
            output_file.flush()
            os.fsync(output_file.fileno())
        os.replace(tmp, path)
        _fsync_directory(path.parent)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


__all__ = [
    "PARKED_RECHECK_SECONDS",
    "ArtifactLinkParkedEntry",
    "append_artifact_link_parked_entries",
    "artifact_link_outbox_parked_path",
    "find_parked_outbox_entry",
    "inspect_artifact_link_parked",
    "parked_artifact_link_keys",
    "parked_entry_from_outbox",
    "read_artifact_link_parked_entries",
    "rewrite_artifact_link_parked_entries",
    "touch_parked_checked_at",
]
