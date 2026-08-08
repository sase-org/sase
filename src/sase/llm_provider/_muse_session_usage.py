"""Token-usage recovery from the Muse session log SASE named.

Muse's ``muse exec --json`` stdout stream carries no token counts at all — the
numbers live in the on-disk session log. Because the provider passes
``--session-id``, that location is deterministic::

    $XDG_DATA_HOME/muse/sessions/YYYY/MM/DD/<session-id>/session.jsonl

The date components are globbed rather than computed from today's date so a run
that spans midnight still resolves.

Usage is summed from ``runtime.session`` events whose ``payload.event.kind`` is
``model_completed``. ``goal_usage_attribution`` events repeat the same numbers
for the same call and are deliberately ignored: counting both would double
every run's token totals.

A missing or unreadable session log is not an error. It degrades to zeroed
usage plus a diagnostic, exactly as a provider with no usage support behaves.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ._subprocess_artifacts import initial_usage_totals, int_usage
from ._tool_call_io import append_tool_call_collector_diagnostic

MUSE_SESSION_PAYLOAD_TYPE = "runtime.session"
MUSE_MODEL_COMPLETED_EVENT_KIND = "model_completed"

_MUSE_DATA_SUBDIR = ("muse", "sessions")
_SESSION_LOG_NAME = "session.jsonl"
# ``sessions/YYYY/MM/DD/<session-id>/session.jsonl``.
_SESSION_LOG_GLOB_PREFIX = "*/*/*"

# Muse usage field -> SASE usage counter. ``cached_tokens`` is the pre-R708
# spelling of ``cache_read_tokens`` and is only consulted as a fallback.
_USAGE_FIELD_MAP = {
    "input_tokens": "input_tokens",
    "output_tokens": "output_tokens",
    "cache_write_tokens": "cache_creation_input_tokens",
}


def _muse_sessions_root() -> Path:
    """Return the root Muse session directory, honoring ``XDG_DATA_HOME``."""
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    return base.joinpath(*_MUSE_DATA_SUBDIR)


def _find_muse_session_log(
    session_id: str, *, sessions_root: Path | None = None
) -> Path | None:
    """Return the session log for *session_id*, or ``None`` when absent."""
    if not session_id:
        return None
    root = sessions_root if sessions_root is not None else _muse_sessions_root()
    pattern = f"{_SESSION_LOG_GLOB_PREFIX}/{session_id}/{_SESSION_LOG_NAME}"
    try:
        return next(iter(sorted(root.glob(pattern))), None)
    except OSError:
        return None


def read_muse_session_usage(
    session_id: str | None,
    *,
    sessions_root: Path | None = None,
    artifacts_dir: str | None = None,
) -> dict[str, int]:
    """Return SASE usage totals recovered from the named session log."""
    totals = initial_usage_totals()
    if not session_id:
        return totals

    artifacts_dir = artifacts_dir or os.environ.get("SASE_ARTIFACTS_DIR")
    log_path = _find_muse_session_log(session_id, sessions_root=sessions_root)
    if log_path is None:
        _record_usage_diagnostic(
            artifacts_dir,
            reason="muse_session_log_not_found",
            extra={"session_id": session_id},
        )
        return totals

    try:
        with log_path.open(encoding="utf-8") as stream:
            for line in stream:
                usage = _model_completed_usage(line)
                if usage is None:
                    continue
                _accumulate_usage(totals, usage)
    except OSError as exc:
        _record_usage_diagnostic(
            artifacts_dir,
            reason="muse_session_log_unreadable",
            extra={"session_id": session_id, "error": str(exc)},
        )
        return initial_usage_totals()

    return totals


def _model_completed_usage(line: str) -> Mapping[str, Any] | None:
    """Return the ``usage`` mapping of a ``model_completed`` session event."""
    line = line.strip()
    if not line:
        return None
    try:
        envelope = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(envelope, Mapping):
        return None
    if envelope.get("payload_type") != MUSE_SESSION_PAYLOAD_TYPE:
        return None

    payload = envelope.get("payload")
    if not isinstance(payload, Mapping):
        return None
    event = payload.get("event")
    if not isinstance(event, Mapping):
        return None
    if event.get("kind") != MUSE_MODEL_COMPLETED_EVENT_KIND:
        return None

    usage = event.get("usage")
    return usage if isinstance(usage, Mapping) else None


def _accumulate_usage(totals: dict[str, int], usage: Mapping[str, Any]) -> None:
    for source_field, target_field in _USAGE_FIELD_MAP.items():
        totals[target_field] += int_usage(usage.get(source_field))

    cache_read = usage.get("cache_read_tokens")
    if cache_read is None:
        cache_read = usage.get("cached_tokens")
    totals["cache_read_input_tokens"] += int_usage(cache_read)


def _record_usage_diagnostic(
    artifacts_dir: str | None,
    *,
    reason: str,
    extra: Mapping[str, Any],
) -> None:
    append_tool_call_collector_diagnostic(
        artifacts_dir, reason=reason, extra=dict(extra)
    )


__all__ = ["read_muse_session_usage"]
