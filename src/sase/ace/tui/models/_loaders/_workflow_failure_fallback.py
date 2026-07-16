"""Failure-detail fallback for workflow runners that die without artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sase.core.agent_launch_facade import safe_launch_name
from sase.core.paths import sharded_path

from .._timestamps import normalize_to_14_digit

_TAIL_LINE_LIMIT = 40
_TAIL_BYTE_LIMIT = 64 * 1024
_FAILURE_EXPLANATION = (
    "Runner exited without recording an error (crash, kill, or startup failure)."
)


@dataclass(frozen=True)
class WorkflowFailureFallback:
    """Fallback message and best raw-output path for one failed workflow."""

    error_message: str
    output_path: str | None


def workflow_output_candidates(
    *,
    cl_name: str,
    launch_timestamp: str,
    recorded_output_path: str | None,
) -> tuple[str, ...]:
    """Return metadata-first output paths, followed by the legacy derivation."""
    candidates: list[str] = []
    if recorded_output_path and recorded_output_path.strip():
        candidates.append(str(Path(recorded_output_path).expanduser()))

    normalized_timestamp = normalize_to_14_digit(launch_timestamp)
    if normalized_timestamp is not None:
        runner_timestamp = f"{normalized_timestamp[2:8]}_{normalized_timestamp[8:]}"
        filename = f"{safe_launch_name(cl_name)}_ace-run-{runner_timestamp}.txt"
        derived_path = sharded_path("workflows", filename, ensure=False)
        if derived_path not in candidates:
            candidates.append(derived_path)

    return tuple(candidates)


def preferred_workflow_output_path(
    *,
    cl_name: str,
    launch_timestamp: str,
    recorded_output_path: str | None,
) -> str | None:
    """Return the metadata path when present, otherwise the derived path."""
    candidates = workflow_output_candidates(
        cl_name=cl_name,
        launch_timestamp=launch_timestamp,
        recorded_output_path=recorded_output_path,
    )
    return candidates[0] if candidates else None


@lru_cache(maxsize=256)
def _read_output_tail_cached(path: str, mtime_ns: int, size: int) -> str:
    """Read a size-capped tail; stat fields form the cache invalidation key."""
    del mtime_ns  # Used only as part of the cache key.
    if size <= 0:
        return ""

    start = max(0, size - _TAIL_BYTE_LIMIT)
    with open(path, "rb") as output_file:
        output_file.seek(start)
        raw_tail = output_file.read(_TAIL_BYTE_LIMIT)

    if start > 0:
        first_newline = raw_tail.find(b"\n")
        if first_newline >= 0:
            raw_tail = raw_tail[first_newline + 1 :]

    decoded = raw_tail.decode("utf-8", errors="replace")
    return "\n".join(decoded.splitlines()[-_TAIL_LINE_LIMIT:]).rstrip()


def _read_output_tail(path: str) -> str:
    try:
        stat = Path(path).stat()
        return _read_output_tail_cached(path, stat.st_mtime_ns, stat.st_size)
    except OSError:
        return ""


def build_workflow_failure_fallback(
    *,
    cl_name: str,
    launch_timestamp: str,
    recorded_output_path: str | None,
) -> WorkflowFailureFallback:
    """Build actionable failure text from a runner log, even when it is absent."""
    candidates = workflow_output_candidates(
        cl_name=cl_name,
        launch_timestamp=launch_timestamp,
        recorded_output_path=recorded_output_path,
    )
    for path in candidates:
        tail = _read_output_tail(path)
        if tail:
            return WorkflowFailureFallback(
                error_message=f"{_FAILURE_EXPLANATION}\nLast output:\n{tail}",
                output_path=path,
            )

    checked = ", ".join(candidates) if candidates else "(no path could be derived)"
    return WorkflowFailureFallback(
        error_message=(
            f"{_FAILURE_EXPLANATION}\n"
            f"No runner output was available. Checked: {checked}"
        ),
        output_path=candidates[0] if candidates else None,
    )
