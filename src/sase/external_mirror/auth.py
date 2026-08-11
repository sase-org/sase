"""Detached-environment tracker-auth evidence for external mirror chops.

The interactive TUI's working ``gh`` proves nothing about the AXE daemon's
detached environment. Every provider listing attempt, success or failure,
records its outcome here so a doctor check can report what the daemon
actually saw instead of assuming an interactive provider call proves the
daemon environment.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from sase.core.paths import sase_subdir
from sase.core.state_write_guard import best_effort_test_state_write_allowed

SCHEMA_VERSION = 1

TrackerProbeOutcome = Literal[
    "ok", "auth_error", "rate_limited", "unavailable", "unsupported"
]
TrackerProbeSource = Literal["chop", "cli"]

_OUTCOMES: frozenset[str] = frozenset(
    {"ok", "auth_error", "rate_limited", "unavailable", "unsupported"}
)
_SOURCES: frozenset[str] = frozenset({"chop", "cli"})

_AUTH_ERROR_MARKERS = (
    "authentication required",
    "authentication failed",
    "gh auth login",
    "bad credentials",
    "not logged into any github hosts",
)
_RATE_LIMIT_MARKERS = ("rate limit",)


@dataclass(frozen=True)
class TrackerProbe:
    """One project's most recently recorded tracker-listing evidence."""

    project: str
    outcome: TrackerProbeOutcome
    source: TrackerProbeSource
    detail: str
    observed_at: str


def _auth_path() -> Path:
    return sase_subdir("external_mirror") / "tracker_auth.json"


def classify_provider_error(error: BaseException) -> TrackerProbeOutcome:
    """Classify a provider exception from its rendered text.

    Provider-specific exception classes (e.g. ``sase_github``'s
    ``GitHubAuthenticationError``) are not importable from this repo, so this
    matches on the same message substrings those classes already surface.
    """
    text = str(error).casefold()
    if any(marker in text for marker in _AUTH_ERROR_MARKERS):
        return "auth_error"
    if any(marker in text for marker in _RATE_LIMIT_MARKERS):
        return "rate_limited"
    return "unavailable"


def record_tracker_probe(
    project: str,
    *,
    outcome: TrackerProbeOutcome,
    source: TrackerProbeSource,
    detail: str = "",
    now: datetime | None = None,
) -> None:
    """Record the outcome of one provider listing attempt."""
    path = _auth_path()
    if not best_effort_test_state_write_allowed(path, category="external-mirror-auth"):
        return
    probes = _read_probes_raw(path)
    probes[project] = {
        "outcome": outcome,
        "source": source,
        "detail": detail,
        "observed_at": (now or datetime.now(UTC)).astimezone(UTC).isoformat(),
    }
    _write_probes_raw(path, probes)


def read_tracker_probes() -> dict[str, TrackerProbe]:
    """Return every project's most recently recorded tracker probe.

    Tolerant of a missing or corrupt file, following :func:`record_tracker_probe`.
    """
    probes = _read_probes_raw(_auth_path())
    result: dict[str, TrackerProbe] = {}
    for project, raw in probes.items():
        if not isinstance(raw, dict):
            continue
        outcome = raw.get("outcome")
        source = raw.get("source")
        if outcome not in _OUTCOMES or source not in _SOURCES:
            continue
        result[project] = TrackerProbe(
            project=project,
            outcome=outcome,
            source=source,
            detail=str(raw.get("detail") or ""),
            observed_at=str(raw.get("observed_at") or ""),
        )
    return result


def _read_probes_raw(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        return {}
    return {key: value for key, value in payload.items() if key != "schema_version"}


def _write_probes_raw(path: Path, probes: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": SCHEMA_VERSION, **probes}
    fd, temp_path_str = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temp_path = Path(temp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temp_path, path)
    except BaseException:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise


__all__ = [
    "SCHEMA_VERSION",
    "TrackerProbe",
    "TrackerProbeOutcome",
    "TrackerProbeSource",
    "classify_provider_error",
    "read_tracker_probes",
    "record_tracker_probe",
]
