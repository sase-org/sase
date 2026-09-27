"""Best-effort ``agent_meta.json["finalizer_status"]`` row-summary tracker.

The tracker holds the C5 summary state in memory and persists it through
``update_meta_field``, touching the turn refresh pulse on transitions so the
Agents tab reloads. Every write is best-effort: failures are swallowed and
never change control flow, verdicts, or result bytes.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

SUMMARY_KEY = "finalizer_status"
SUMMARY_SCHEMA_VERSION = 1
MAX_SUMMARY_INSTANCES = 16
SUMMARY_STRING_CAP = 120
STEP_WRITE_THROTTLE_SECONDS = 2.0

_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b")
_URL_RE = re.compile(r"https?://\S+")
_BEAD_RE = re.compile(r"\bsase-[0-9A-Za-z][0-9A-Za-z._-]*")


def _cap_text(value: Any, limit: int = SUMMARY_STRING_CAP) -> str | None:
    """Cap *value* to *limit* characters on a char boundary, or pass None."""
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    if len(text) <= limit:
        return text
    return text[:limit]


def _choose_headline(
    *,
    sha: str | None = None,
    url: str | None = None,
    bead_id: str | None = None,
    exit_code: int | None = None,
) -> str | None:
    """Pick the generic headline: SHA, then URL, then bead id, then exit code."""
    if sha:
        return _cap_text(f"commit {sha[:12]}")
    if url:
        return _cap_text(url)
    if bead_id:
        return _cap_text(bead_id)
    if exit_code is not None:
        return _cap_text(f"exit {exit_code}")
    return None


def headline_from_evidence(
    evidence: Any,
    *,
    exit_code: int | None = None,
) -> str | None:
    """Choose a headline from typed outcome evidence plus an exit code."""
    sha: str | None = None
    url: str | None = None
    bead_id: str | None = None
    items = evidence if isinstance(evidence, (list, tuple)) else []
    for item in items:
        kind = getattr(item, "kind", None)
        value = getattr(item, "value", None)
        if isinstance(item, dict):
            kind = item.get("kind", kind)
            value = item.get("value", value)
        if not isinstance(value, str) or not value:
            continue
        lowered_kind = str(kind or "").lower()
        if lowered_kind in {"sha", "commit", "commit_sha"} and sha is None:
            match = _SHA_RE.search(value) or _SHA_RE.search(value.lower())
            sha = (match.group(0) if match else value)[:12]
        elif lowered_kind in {"url", "pr_url", "link"} and url is None:
            match = _URL_RE.search(value)
            url = match.group(0) if match else value
        elif lowered_kind in {"bead", "bead_id"} and bead_id is None:
            match = _BEAD_RE.search(value)
            bead_id = match.group(0) if match else value
        else:
            if sha is None:
                match = _SHA_RE.search(value)
                if match:
                    sha = match.group(0)[:12]
                    continue
            if url is None:
                match = _URL_RE.search(value)
                if match:
                    url = match.group(0)
                    continue
            if bead_id is None:
                match = _BEAD_RE.search(value)
                if match:
                    bead_id = match.group(0)
    return _choose_headline(sha=sha, url=url, bead_id=bead_id, exit_code=exit_code)


def reason_for_result(result: Any) -> str | None:
    """Fill the per-instance ``reason`` for a terminal instance result."""
    status = getattr(result, "status", None)
    if status == "failed":
        diagnostics = getattr(result, "diagnostics", None) or []
        for diagnostic in diagnostics:
            severity = (
                diagnostic.get("severity")
                if isinstance(diagnostic, dict)
                else getattr(diagnostic, "severity", None)
            )
            message = (
                diagnostic.get("message")
                if isinstance(diagnostic, dict)
                else getattr(diagnostic, "message", None)
            )
            if severity == "error" and isinstance(message, str) and message.strip():
                return _cap_text(message.strip())
        stderr_tail = getattr(result, "stderr_tail", None)
        if isinstance(stderr_tail, str):
            lines = [line for line in stderr_tail.splitlines() if line.strip()]
            if lines:
                return _cap_text(lines[-1].strip())
        for diagnostic in diagnostics:
            message = (
                diagnostic.get("message")
                if isinstance(diagnostic, dict)
                else getattr(diagnostic, "message", None)
            )
            if isinstance(message, str) and message.strip():
                return _cap_text(message.strip())
        return None
    if status == "deferred":
        deferral = getattr(result, "deferral", None)
        reason = (
            deferral.get("reason")
            if isinstance(deferral, dict)
            else getattr(deferral, "reason", None)
        )
        paths = (
            deferral.get("paths")
            if isinstance(deferral, dict)
            else getattr(deferral, "paths", None)
        )
        count = len(paths) if isinstance(paths, (list, tuple)) else 0
        if isinstance(reason, str) and reason:
            return _cap_text(f"{reason} · {count} paths")
        return None
    if status == "refused":
        refusal = getattr(result, "refusal_reason", None)
        if isinstance(refusal, str) and refusal:
            return _cap_text(refusal)
        return None
    if status == "not_run":
        blocked_by = getattr(result, "blocked_by", None)
        if isinstance(blocked_by, str) and blocked_by:
            return _cap_text(f"blocked by {blocked_by}")
        return None
    return None


def count_result_warnings(result: Any) -> int:
    """Count warn steps plus warning diagnostics in the latest attempt."""
    warnings = 0
    warn_steps = getattr(result, "warn_steps", 0)
    if isinstance(warn_steps, (int, float)) and warn_steps > 0:
        warnings += int(warn_steps)
    diagnostics = getattr(result, "diagnostics", None) or []
    attempts = getattr(result, "attempts", None) or []
    latest: Any = attempts[-1].attempt if attempts else None
    if latest is None and hasattr(attempts, "__iter__"):
        latest = None
    for diagnostic in diagnostics:
        severity = (
            diagnostic.get("severity")
            if isinstance(diagnostic, dict)
            else getattr(diagnostic, "severity", None)
        )
        attempt = (
            diagnostic.get("attempt")
            if isinstance(diagnostic, dict)
            else getattr(diagnostic, "attempt", None)
        )
        if severity != "warning":
            continue
        if latest is not None and attempt is not None and attempt != latest:
            continue
        warnings += 1
    return warnings


class FinalizerStatusTracker:
    """In-memory C5 summary state with best-effort ``agent_meta`` writes."""

    def __init__(self, artifacts_dir: str | None) -> None:
        self._artifacts_dir = artifacts_dir
        self._phase: str | None = None
        self._reason: str | None = None
        self._status: str | None = None
        self._plan_digest: str | None = None
        self._run_id: str | None = None
        self._started_at: float | None = None
        self._runner: dict[str, Any] | None = None
        self._instances: dict[str, dict[str, Any]] = {}
        self._instance_order: list[str] = []
        self._instance_count = 0
        self._last_step_write = 0.0
        self._pending_step: dict[str, dict[str, Any]] = {}

    def seal_planned(
        self,
        *,
        plan_digest: str | None,
        instance_ids: list[str] | tuple[str, ...],
    ) -> None:
        """Record the plan-seal ``planned`` summary with every instance planned."""
        now = time.time()
        if self._started_at is None:
            self._started_at = now
        self._phase = "planned"
        self._reason = None
        self._status = None
        self._plan_digest = plan_digest
        ids = list(instance_ids)
        self._instance_count = len(ids)
        self._instances = {}
        self._instance_order = []
        for instance_id in ids[:MAX_SUMMARY_INSTANCES]:
            self._instances[instance_id] = {
                "id": instance_id,
                "status": "planned",
                "attempt": 0,
                "max_attempts": 0,
                "op": None,
                "step": None,
                "started_at": None,
                "finished_at": None,
                "headline": None,
                "warnings": 0,
                "reason": None,
            }
            self._instance_order.append(instance_id)
        self._write(force=True)

    def mark_declaring(
        self,
        *,
        run_id: str,
        plan_digest: str | None,
        runner: dict[str, Any] | None = None,
    ) -> None:
        """Record ``phase_started``: the run is declaring."""
        now = time.time()
        if self._started_at is None:
            self._started_at = now
        self._phase = "declaring"
        self._run_id = run_id
        if plan_digest is not None:
            self._plan_digest = plan_digest
        if runner is not None:
            self._runner = runner
        self._write(force=True)

    def mark_executing(self) -> None:
        """Move the summary to ``executing`` when the first instance starts."""
        if self._phase == "executing":
            return
        self._phase = "executing"
        self._write(force=True)

    def _ensure_instance(self, instance_id: str) -> dict[str, Any]:
        entry = self._instances.get(instance_id)
        if entry is not None:
            return entry
        if len(self._instance_order) < MAX_SUMMARY_INSTANCES:
            entry = {
                "id": instance_id,
                "status": "waiting",
                "attempt": 0,
                "max_attempts": 0,
                "op": None,
                "step": None,
                "started_at": None,
                "finished_at": None,
                "headline": None,
                "warnings": 0,
                "reason": None,
            }
            self._instances[instance_id] = entry
            self._instance_order.append(instance_id)
            self._instance_count = max(self._instance_count, len(self._instance_order))
            return entry
        if self._instance_order:
            return self._instances[self._instance_order[0]]
        entry = {
            "id": instance_id,
            "status": "waiting",
            "attempt": 0,
            "max_attempts": 0,
            "op": None,
            "step": None,
            "started_at": None,
            "finished_at": None,
            "headline": None,
            "warnings": 0,
            "reason": None,
        }
        return entry

    def note_instance_started(
        self,
        instance_id: str,
        *,
        attempt: int = 0,
        max_attempts: int = 0,
        op: str | None = None,
    ) -> None:
        """Record an instance transition to running."""
        self.mark_executing()
        entry = self._ensure_instance(instance_id)
        entry["status"] = "running"
        if attempt:
            entry["attempt"] = attempt
        if max_attempts:
            entry["max_attempts"] = max_attempts
        if op is not None:
            entry["op"] = _cap_text(op)
        if entry.get("started_at") is None:
            entry["started_at"] = time.time()
        self._write(force=True)

    def note_instance_finished(
        self,
        instance_id: str,
        *,
        status: str,
        reason: str | None = None,
        headline: str | None = None,
        warnings: int = 0,
        attempt: int = 0,
        max_attempts: int = 0,
    ) -> None:
        """Record an instance terminal transition."""
        entry = self._ensure_instance(instance_id)
        entry["status"] = status
        entry["reason"] = _cap_text(reason)
        if headline is not None:
            entry["headline"] = _cap_text(headline)
        entry["warnings"] = max(0, int(warnings or 0))
        if attempt:
            entry["attempt"] = attempt
        if max_attempts:
            entry["max_attempts"] = max_attempts
        entry["finished_at"] = time.time()
        self.flush_pending_step(instance_id)
        self._write(force=True)

    def note_attempt_started(
        self,
        instance_id: str,
        attempt: int,
        max_attempts: int,
    ) -> None:
        """Record an attempt allocation."""
        self.mark_executing()
        entry = self._ensure_instance(instance_id)
        entry["status"] = "running"
        entry["attempt"] = attempt
        entry["max_attempts"] = max_attempts
        if entry.get("started_at") is None:
            entry["started_at"] = time.time()
        self._write(force=True)

    def note_attempt_finished(
        self,
        instance_id: str,
        attempt: int,
        *,
        status: str,
        code: str | None = None,
    ) -> None:
        """Record an attempt settlement without closing the instance."""
        entry = self._ensure_instance(instance_id)
        entry["attempt"] = attempt
        if status != "success" and code:
            entry["reason"] = _cap_text(code)
        self.flush_pending_step(instance_id)
        self._write(force=True)

    def note_op(
        self,
        instance_id: str,
        op: str,
        *,
        step: str | None = None,
    ) -> None:
        """Record the current operation label; the write is forced."""
        entry = self._ensure_instance(instance_id)
        entry["op"] = _cap_text(op)
        if step is not None:
            entry["step"] = _cap_text(step)
            self._pending_step.pop(instance_id, None)
        self._write(force=True)

    def note_step(
        self,
        instance_id: str,
        step: str,
        *,
        warnings: int | None = None,
    ) -> None:
        """Record a step update, throttled to one write every 2 s."""
        entry = self._ensure_instance(instance_id)
        entry["step"] = _cap_text(step)
        if warnings is not None:
            entry["warnings"] = max(0, int(warnings))
        self._pending_step[instance_id] = entry
        self._write(step_only=True)

    def flush_pending_step(self, instance_id: str) -> None:
        """Flush a throttled step value; always persisted at op end."""
        self._pending_step.pop(instance_id, None)

    def flush_steps(self) -> None:
        """Flush all throttled step values."""
        if self._pending_step:
            self._pending_step = {}
            self._write(force=True)

    def mark_settled(self, *, status: str, reason: str | None = None) -> None:
        """Record the terminal ``settled`` summary."""
        self.flush_steps()
        self._phase = "settled"
        self._status = status
        self._reason = _cap_text(reason)
        self._write(force=True)

    def mark_skipped(self, *, reason: str) -> None:
        """Record the handoff ``skipped`` summary."""
        self._phase = "skipped"
        self._reason = _cap_text(reason)
        self._status = None
        self._write(force=True)

    def payload(self) -> dict[str, Any]:
        """Return the current summary payload without writing."""
        now = time.time()
        return {
            "schema_version": SUMMARY_SCHEMA_VERSION,
            "phase": self._phase,
            "reason": self._reason,
            "status": self._status,
            "plan_digest": self._plan_digest,
            "run_id": self._run_id,
            "started_at": self._started_at,
            "updated_at": now,
            "runner": dict(self._runner) if self._runner else None,
            "instances": [
                dict(self._instances[instance_id])
                for instance_id in self._instance_order
            ],
            "instance_count": self._instance_count,
        }

    def _write(self, *, force: bool = False, step_only: bool = False) -> None:
        if not self._artifacts_dir:
            return
        now = time.time()
        if step_only and not force:
            if now - self._last_step_write < STEP_WRITE_THROTTLE_SECONDS:
                return
            self._last_step_write = now
        try:
            from sase.axe.run_agent_helpers import update_meta_field
            from sase.turns.settlement import (
                project_name_from_artifacts_dir,
                touch_turn_refresh_pulse,
            )

            update_meta_field(self._artifacts_dir, SUMMARY_KEY, self.payload())
            touch_turn_refresh_pulse(
                project_name_from_artifacts_dir(self._artifacts_dir)
            )
        except Exception:  # noqa: BLE001 - summary writes are best-effort
            logger.debug("finalizer status summary write failed", exc_info=True)


__all__ = [
    "MAX_SUMMARY_INSTANCES",
    "STEP_WRITE_THROTTLE_SECONDS",
    "SUMMARY_KEY",
    "SUMMARY_SCHEMA_VERSION",
    "SUMMARY_STRING_CAP",
    "FinalizerStatusTracker",
    "count_result_warnings",
    "headline_from_evidence",
    "reason_for_result",
]
