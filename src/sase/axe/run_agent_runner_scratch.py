"""Best-effort cleanup for one runner's launch-assigned scratch."""

from __future__ import annotations

import json
import os
import stat
import traceback
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.dismissed_agent_completion import SHELL_HANDOFF_OUTCOMES
from sase.core.managed_tmp_reaper import (
    LAUNCH_SCRATCH_OBSERVER_PROCFS,
    LaunchScratchLiveness,
    LaunchScratchRequest,
    observe_launch_scratch_liveness,
    reap_managed_tmpdir,
)
from sase.core.paths import managed_tmpdir_root
from sase.env_contracts import SASE_LAUNCH_SCRATCH_KEY_ENV

_CANDIDATE_BUCKETS: tuple[tuple[str, str], ...] = (
    ("cargo-targets", "CARGO_TARGET_DIR"),
    ("agent-tmp", "TMPDIR"),
)
_BUCKET_ENV_VARS = dict(_CANDIDATE_BUCKETS)
_LAUNCH_SCRATCH_BUCKETS = ("cargo-targets", "agent-tmp")
_LAUNCH_SCRATCH_BUCKET_SET = frozenset(_LAUNCH_SCRATCH_BUCKETS)


@dataclass(frozen=True)
class _LaunchScratchCandidate:
    bucket: str
    path: Path


def cleanup_launch_scratch(
    *,
    exec_outcome: str,
    proc_root: Path | None = None,
) -> None:
    """Remove this runner's managed scratch when no live process still owns it."""
    try:
        _cleanup_launch_scratch(exec_outcome=exec_outcome, proc_root=proc_root)
    except Exception as exc:
        _emit_cleanup_line(
            status="error",
            scratch_key=os.environ.get(SASE_LAUNCH_SCRATCH_KEY_ENV),
            context="runner-exit",
            error=f"{type(exc).__qualname__}: {exc}",
            error_traceback=traceback.format_exc(),
        )


def _cleanup_launch_scratch(
    *,
    exec_outcome: str,
    proc_root: Path | None,
) -> None:
    scratch_key = os.environ.get(SASE_LAUNCH_SCRATCH_KEY_ENV)
    # Staged adoption uses the real outcome (``completed``/``failed``), never a
    # shell-handoff outcome, so its scratch cleans normally. Held-run evidence
    # (stage, archived proposal, receipts, failed done marker) lives in the
    # artifacts dir and is preserved by the failure hold, not by this scratch.
    if exec_outcome in SHELL_HANDOFF_OUTCOMES:
        # Monitor settlement owns the starter's cargo target after a monitor
        # handoff; gate handoffs continue to the dead-launch backstop.
        _emit_cleanup_line(
            status="skipped",
            scratch_key=scratch_key,
            reason=f"shell-handoff:{exec_outcome}",
            context="runner-exit",
        )
        return
    cleanup_launch_scratch_key(
        scratch_key,
        buckets=_LAUNCH_SCRATCH_BUCKETS,
        expected_env_vars=_BUCKET_ENV_VARS,
        context="runner-exit",
        proc_root=proc_root,
    )


def cleanup_launch_scratch_key(
    scratch_key: str | None,
    *,
    buckets: tuple[str, ...],
    context: str,
    expected_env_vars: Mapping[str, str] | None = None,
    proc_root: Path | None = None,
    skip_reason: str | None = None,
    error: str | None = None,
) -> None:
    """Best-effort cleanup for selected buckets owned by one launch key.

    Runner exit supplies its exported path variables as an extra ownership
    check. Monitor settlement instead uses the starter's recorded key and only
    asks to reclaim its cargo target.
    """
    try:
        _cleanup_launch_scratch_key(
            scratch_key,
            buckets=buckets,
            context=context,
            expected_env_vars=expected_env_vars,
            proc_root=proc_root,
            skip_reason=skip_reason,
            error=error,
        )
    except Exception as exc:
        _emit_cleanup_line(
            status="error",
            scratch_key=scratch_key,
            context=context,
            error=f"{type(exc).__qualname__}: {exc}",
            error_traceback=traceback.format_exc(),
        )


def _cleanup_launch_scratch_key(
    scratch_key: str | None,
    *,
    buckets: tuple[str, ...],
    context: str,
    expected_env_vars: Mapping[str, str] | None,
    proc_root: Path | None,
    skip_reason: str | None,
    error: str | None,
) -> None:
    if error is not None:
        _emit_cleanup_line(
            status="error",
            scratch_key=scratch_key,
            reason=skip_reason,
            context=context,
            error=error,
        )
        return
    if not scratch_key:
        _emit_cleanup_line(
            status="skipped",
            scratch_key=None,
            reason=skip_reason or "no-scratch-key",
            context=context,
        )
        return
    if Path(scratch_key).name != scratch_key or scratch_key in {".", ".."}:
        _emit_cleanup_line(
            status="skipped",
            scratch_key=scratch_key,
            reason="invalid-scratch-key",
            context=context,
        )
        return
    if not buckets or any(
        bucket not in _LAUNCH_SCRATCH_BUCKET_SET for bucket in buckets
    ):
        _emit_cleanup_line(
            status="skipped",
            scratch_key=scratch_key,
            reason="unsupported-bucket",
            context=context,
        )
        return

    managed_root = managed_tmpdir_root()
    candidates = tuple(
        _launch_scratch_candidates(
            scratch_key=scratch_key,
            root=managed_root,
            buckets=buckets,
            expected_env_vars=expected_env_vars,
        )
    )
    if not candidates:
        _emit_cleanup_line(
            status="skipped",
            scratch_key=scratch_key,
            reason=skip_reason or "no-matching-candidates",
            context=context,
        )
        return
    observation = observe_launch_scratch_liveness(
        tuple((scratch_key, candidate.path) for candidate in candidates),
        proc_root=proc_root,
    )
    complete = observation.observer == LAUNCH_SCRATCH_OBSERVER_PROCFS and all(
        candidate.complete for candidate in observation.candidates
    )
    live = any(candidate.live for candidate in observation.candidates)
    liveness = LaunchScratchLiveness(
        live=live,
        complete=complete,
        diagnostics=observation.diagnostics,
    )
    result = reap_managed_tmpdir(
        managed_root,
        age_reap=False,
        pressure_reap=False,
        max_removals=len(candidates),
        launch_scratch=LaunchScratchRequest(
            scratch_key=scratch_key,
            buckets=tuple(candidate.bucket for candidate in candidates),
            liveness=liveness,
        ),
        # This request reaps only the selected launch key and buckets. The
        # hourly dead-launch backstop owns all other launch scratch.
        dead_launch_enabled=False,
    )
    _emit_cleanup_line(
        status="preserved" if (live or not complete) else "removed",
        scratch_key=scratch_key,
        context=context,
        observer=observation.observer,
        live=live,
        removed=result.launch_removed,
        removed_bytes=result.launch_reclaimed_bytes,
        skipped=result.skipped,
        skip_reasons=result.skip_reasons,
        incomplete_observations=result.incomplete_observations,
    )


def _emit_cleanup_line(
    *,
    status: str,
    scratch_key: str | None,
    reason: str | None = None,
    observer: str | None = None,
    live: bool | None = None,
    removed: int = 0,
    removed_bytes: int = 0,
    skipped: int = 0,
    skip_reasons: tuple[str, ...] = (),
    incomplete_observations: int = 0,
    context: str | None = None,
    error: str | None = None,
    error_traceback: str | None = None,
) -> None:
    """Log one structured ``launch_scratch_cleanup`` line for the caller.

    Never raises: cleanup logging must not take down process settlement.
    """
    try:
        payload: dict[str, Any] = {
            "event": "launch_scratch_cleanup",
            "status": status,
            "scratch_key": scratch_key,
        }
        if context is not None:
            payload["context"] = context
        if reason is not None:
            payload["reason"] = reason
        if observer is not None:
            payload["observer"] = observer
        if live is not None:
            payload["live"] = live
        payload["removed"] = removed
        payload["removed_bytes"] = removed_bytes
        payload["skipped"] = skipped
        if skip_reasons:
            payload["skip_reasons"] = list(skip_reasons)
        if incomplete_observations:
            payload["incomplete_observations"] = incomplete_observations
        if error is not None:
            payload["error"] = error
        if error_traceback is not None:
            payload["traceback"] = error_traceback
        print(json.dumps(payload, sort_keys=True), flush=True)
    except Exception:
        return


def _launch_scratch_candidates(
    *,
    scratch_key: str,
    root: Path,
    buckets: tuple[str, ...],
    expected_env_vars: Mapping[str, str] | None,
) -> Iterable[_LaunchScratchCandidate]:
    for bucket in buckets:
        bucket_dir = root / bucket
        candidate = bucket_dir / scratch_key
        if candidate.parent != bucket_dir:
            continue
        env_var = expected_env_vars.get(bucket) if expected_env_vars else None
        if env_var is not None:
            expected = _normalized_absolute_path(candidate)
            if _normalized_absolute_path(os.environ.get(env_var, "")) != expected:
                continue
        try:
            mode = os.lstat(candidate).st_mode
        except OSError:
            continue
        if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
            continue
        yield _LaunchScratchCandidate(bucket=bucket, path=candidate)


def _normalized_absolute_path(value: str | Path) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        return path.resolve(strict=False)
    except OSError:
        return path.absolute()
