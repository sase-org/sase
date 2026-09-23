"""Best-effort passive Claude usage events from stream output."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Mapping
from typing import Any

from sase.llm_provider.usage._claude_constants import (
    CLAUDE_PASSIVE_FLUSH_SECONDS,
    CLAUDE_PASSIVE_QUEUE_LIMIT,
    CLAUDE_PROVIDER_NAME,
)
from sase.llm_provider.usage._claude_support import (
    ClaudeCommandResult,
    ClaudeCommandRunner,
    auth_info_from_result,
    event_window,
    is_finite_number,
    optional_epoch_seconds,
    resolve_claude_executable,
    safe_run,
    vendor_state_from_rate_limit_info,
)
from sase.llm_provider.usage.config import collection_skip_reason
from sase.llm_provider.usage.probe import record_passive_usage_observation
from sase.llm_provider.usage.refresh import USAGE_REFRESH_CONTEXT_ID
from sase.llm_provider.usage.store import (
    prepare_provider_usage_account_context,
    record_provider_usage_observation,
)
from sase.llm_provider.usage.types import (
    UsageProbeContext,
    observation_schema_version,
    validate_observation,
)

log = logging.getLogger(__name__)


def capture_passive_context(
    *,
    executable: str | None = None,
    run: ClaudeCommandRunner,
    clock: Callable[[], float] = time.time,
) -> UsageProbeContext | None:
    """Prepare a generation-fenced context for Claude stream usage events."""
    if collection_skip_reason(CLAUDE_PROVIDER_NAME) is not None:
        return None
    resolved = resolve_claude_executable(executable)
    if resolved is None:
        return None
    now = clock()
    auth_result = safe_run(
        run,
        (resolved, "auth", "status", "--json"),
        cwd=None,
        deadline_at=now + 2.0,
    )
    if not isinstance(auth_result, ClaudeCommandResult):
        return None
    auth_info = auth_info_from_result(auth_result)
    if auth_info.mode != "subscription" or not auth_info.context_material:
        return None
    try:
        prepared = prepare_provider_usage_account_context(
            CLAUDE_PROVIDER_NAME,
            USAGE_REFRESH_CONTEXT_ID,
            now=now,
        )
    except Exception:
        log.debug("Claude passive usage account context was unavailable")
        return None
    return UsageProbeContext(
        schema_version=observation_schema_version(),
        provider=CLAUDE_PROVIDER_NAME,
        deadline_at=now + 2.0,
        context_id=prepared.context_id,
        account_generation=prepared.account_generation,
        operation_id=f"claude-stream-{uuid.uuid4().hex[:12]}",
        request_started_at=now,
        executable=resolved,
        auth_context=USAGE_REFRESH_CONTEXT_ID,
    )


def claude_rate_limit_event_observation(
    event: Mapping[str, Any],
    context: UsageProbeContext,
    *,
    now: float,
) -> dict[str, Any] | None:
    """Normalize one Claude ``rate_limit_event`` into a partial observation."""
    if event.get("type") != "rate_limit_event" or context.provider != "claude":
        return None
    info = event.get("rate_limit_info")
    if not isinstance(info, Mapping):
        return None
    raw_windows = info.get("unifiedWindows")
    if not isinstance(raw_windows, Mapping):
        return None

    windows: list[dict[str, Any]] = []
    malformed = False
    for raw_key, raw_window in raw_windows.items():
        if not isinstance(raw_key, str) or not isinstance(raw_window, Mapping):
            malformed = True
            continue
        utilization = raw_window.get("utilization")
        if (
            isinstance(utilization, bool)
            or not isinstance(utilization, int | float)
            or not is_finite_number(utilization)
        ):
            malformed = True
            continue
        utilization_value = float(utilization)
        if utilization_value < 0.0:
            malformed = True
            continue
        resets_at = optional_epoch_seconds(raw_window.get("resetsAt"))
        if resets_at == "malformed":
            malformed = True
            resets_at = None
        window = event_window(raw_key, utilization_value * 100.0, resets_at, now)
        window["vendor_state"] = vendor_state_from_rate_limit_info(info)
        windows.append(window)

    if not windows:
        return None
    observation = {
        "schema_version": context.schema_version,
        "provider": CLAUDE_PROVIDER_NAME,
        "context_id": context.context_id,
        "account_generation": context.account_generation,
        "ordering_token": now,
        "received_at": now,
        "source": "stream_event",
        "outcome": "ok",
        "reason_code": "parse_error" if malformed else None,
        "diagnostic": (
            "some Claude rate-limit windows could not be parsed" if malformed else None
        ),
        "completeness": "partial",
        "authoritative_empty": False,
        "account_mode": "subscription",
        "plan": None,
        "windows": windows,
    }
    try:
        return validate_observation(observation, now=now)
    except (TypeError, ValueError, AttributeError):
        return None


def submit_claude_passive_usage_event(
    event: Mapping[str, Any],
    context: UsageProbeContext | None,
) -> None:
    """Queue a Claude stream event for best-effort usage persistence."""
    if context is None:
        return
    try:
        observation = claude_rate_limit_event_observation(
            event,
            context,
            now=time.time(),
        )
    except Exception:
        log.debug("Claude passive usage event was ignored")
        return
    if observation is not None:
        _PASSIVE_SINK.submit(observation)


def flush_claude_passive_usage_events(
    timeout: float = CLAUDE_PASSIVE_FLUSH_SECONDS,
) -> None:
    """Best-effort bounded flush for queued Claude usage stream events."""
    _PASSIVE_SINK.flush(timeout)


class _PassiveUsageSink:
    """Bounded background sink for stream-fed usage observations."""

    def __init__(self) -> None:
        self._pending: deque[Mapping[str, Any]] = deque()
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._thread: threading.Thread | None = None
        self._active = 0

    def submit(self, observation: Mapping[str, Any]) -> None:
        with self._lock:
            if len(self._pending) >= CLAUDE_PASSIVE_QUEUE_LIMIT:
                self._pending.popleft()
            self._pending.append(dict(observation))
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run,
                    name="sase-claude-passive-usage",
                    daemon=True,
                )
                self._thread.start()
            self._event.set()

    def flush(self, timeout: float) -> None:
        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            with self._lock:
                if not self._pending and self._active == 0:
                    return
            time.sleep(0.01)

    def _run(self) -> None:
        while True:
            self._event.wait()
            while True:
                with self._lock:
                    if not self._pending:
                        self._event.clear()
                        break
                    observation = self._pending.popleft()
                    self._active += 1
                try:
                    _persist_passive_observation(observation)
                finally:
                    with self._lock:
                        self._active -= 1


def _persist_passive_observation(observation: Mapping[str, Any]) -> None:
    try:
        validated = record_passive_usage_observation(observation, now=time.time())
        if validated is not None:
            record_provider_usage_observation(validated, now=time.time())
    except Exception:
        log.debug("Claude passive usage observation could not be persisted")


_PASSIVE_SINK = _PassiveUsageSink()


__all__ = [
    "capture_passive_context",
    "claude_rate_limit_event_observation",
    "flush_claude_passive_usage_events",
    "submit_claude_passive_usage_event",
]
