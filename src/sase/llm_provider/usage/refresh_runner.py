"""Durable usage-refresh runner. Invoked as ``python -m sase.llm_provider.usage.refresh_runner``."""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Mapping
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any

from sase.llm_provider.usage.probe import default_probe_context, run_usage_probe
from sase.llm_provider.usage.refresh import (
    MAX_CONCURRENT_USAGE_PROBES,
    USAGE_REFRESH_BATCH_DEADLINE_SECONDS,
    USAGE_REFRESH_OPERATION,
    USAGE_REFRESH_PROVIDER_DEADLINE_SECONDS,
)
from sase.llm_provider.usage.store import (
    record_provider_usage_observation,
    record_provider_usage_refresh_attempt,
    release_provider_usage_refresh,
)
from sase.llm_provider.usage.types import (
    UsageProbeContext,
    UsageReasonCode,
    validated_status_observation,
)
from sase.ops.cli import finish_operation, load_request

log = logging.getLogger(__name__)

_CLEANUP_SECONDS = 2.0


def main(argv: list[str] | None = None) -> int:  # noqa: ARG001
    """Run admitted provider probes and persist sanitized observations."""
    request = load_request(USAGE_REFRESH_OPERATION, required=True)
    payload = dict(request.payload)
    started = time.time()
    try:
        results = _run_admitted_refresh(payload, now=started)
    except Exception as exc:
        log.warning("usage refresh runner failed", exc_info=True)
        return finish_operation(
            operation=USAGE_REFRESH_OPERATION,
            success=False,
            message="usage refresh failed",
            error=str(exc),
            payload={"providers": []},
        )
    return finish_operation(
        operation=USAGE_REFRESH_OPERATION,
        success=True,
        message="usage refresh completed",
        payload={"providers": results},
    )


def _run_admitted_refresh(
    payload: Mapping[str, Any],
    *,
    now: float | None = None,
) -> list[dict[str, Any]]:
    """Execute the admitted provider set with bounded concurrency and deadlines."""
    started = time.time() if now is None else now
    jobs = _jobs_from_payload(payload)
    max_concurrent = _positive_int(
        payload.get("max_concurrent"), MAX_CONCURRENT_USAGE_PROBES
    )
    batch_deadline = _positive_float(
        payload.get("batch_deadline_seconds"),
        USAGE_REFRESH_BATCH_DEADLINE_SECONDS,
    )
    provider_deadline = _positive_float(
        payload.get("provider_deadline_seconds"),
        USAGE_REFRESH_PROVIDER_DEADLINE_SECONDS,
    )
    cadence = _positive_float(payload.get("cadence_seconds"), 300.0)
    plugin_specs = payload.get("plugin_specs")
    specs = plugin_specs if isinstance(plugin_specs, dict) else {}
    work_deadline = started + max(batch_deadline - _CLEANUP_SECONDS, 1.0)
    pending = list(jobs)
    results: list[dict[str, Any]] = []
    in_flight: dict[Any, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max_concurrent) as pool:
        while pending or in_flight:
            clock = time.time()
            while pending and len(in_flight) < max_concurrent and clock < work_deadline:
                job = pending.pop(0)
                remaining = max(work_deadline - clock, 0.1)
                deadline_seconds = min(provider_deadline, remaining)
                future = pool.submit(
                    _run_one_provider,
                    job,
                    specs.get(job["provider"]) or job.get("plugin_spec"),
                    deadline_seconds,
                    cadence,
                    clock,
                )
                in_flight[future] = job
                clock = time.time()
            if not in_flight:
                break
            wait_timeout = max(work_deadline - time.time(), 0.05)
            done, _ = wait(
                tuple(in_flight),
                timeout=wait_timeout,
                return_when=FIRST_COMPLETED,
            )
            if not done:
                break
            for future in done:
                job = in_flight.pop(future)
                try:
                    results.append(future.result())
                except Exception:
                    log.warning(
                        "usage refresh probe crashed for %r",
                        job.get("provider"),
                        exc_info=True,
                    )
                    results.append(_deadline_result(job, time.time(), "probe_failed"))
                    _finish_job(job, "error", cadence, time.time())
    clock = time.time()
    for job in pending:
        results.append(_deadline_result(job, clock, "deadline_exceeded"))
        _finish_job(job, "error", cadence, clock)
    for future, job in list(in_flight.items()):
        future.cancel()
        results.append(_deadline_result(job, clock, "deadline_exceeded"))
        _finish_job(job, "error", cadence, clock)
    return results


def _run_one_provider(
    job: Mapping[str, Any],
    plugin_spec: Mapping[str, Any] | None,
    deadline_seconds: float,
    cadence: float,
    now: float,
) -> dict[str, Any]:
    provider = str(job["provider"])
    context = _probe_context(job, deadline_seconds, now)
    spec = dict(plugin_spec) if isinstance(plugin_spec, dict) else None
    result = run_usage_probe(
        context,
        isolate=True,
        plugin_spec=spec,
        now=now,
    )
    observation = result.observation
    if observation is None:
        observation = validated_status_observation(
            context,
            now=time.time(),
            outcome="error",
            reason_code="probe_failed",
            diagnostic=result.skipped or "usage collection is disabled",
        )
    try:
        record_provider_usage_observation(observation, now=time.time())
    except Exception:
        log.warning(
            "could not persist usage observation for %r", provider, exc_info=True
        )
    outcome = str(observation.get("outcome") or "error")
    _finish_job(job, outcome, cadence, time.time())
    return {
        "provider": provider,
        "outcome": outcome,
        "reason_code": observation.get("reason_code"),
        "skipped": result.skipped,
    }


def _probe_context(
    job: Mapping[str, Any], deadline_seconds: float, now: float
) -> UsageProbeContext:
    return default_probe_context(
        str(job["provider"]),
        now=now,
        deadline_seconds=deadline_seconds,
        context_id=str(job.get("context_id") or "default"),
        account_generation=int(job.get("account_generation") or 1),
        operation_id=str(job.get("lease_id") or "op"),
    )


def _finish_job(
    job: Mapping[str, Any], outcome: str, cadence: float, now: float
) -> None:
    provider = str(job.get("provider") or "")
    context_id = str(job.get("context_id") or "default")
    generation = int(job.get("account_generation") or 1)
    lease_id = job.get("lease_id")
    try:
        record_provider_usage_refresh_attempt(
            provider,
            context_id,
            generation,
            outcome,
            cadence_seconds=cadence,
            now=now,
        )
    except Exception:
        log.debug("could not record usage refresh attempt for %r", provider)
    if isinstance(lease_id, str) and lease_id:
        try:
            release_provider_usage_refresh(
                provider, context_id, generation, lease_id, now=now
            )
        except Exception:
            log.debug("could not release usage refresh lease for %r", provider)


def _deadline_result(
    job: Mapping[str, Any], now: float, reason_code: UsageReasonCode
) -> dict[str, Any]:
    context = _probe_context(job, 0.1, now)
    observation = validated_status_observation(
        context,
        now=now,
        outcome="error",
        reason_code=reason_code,
    )
    try:
        record_provider_usage_observation(observation, now=now)
    except Exception:
        log.debug("could not persist deadline observation for %r", job.get("provider"))
    return {
        "provider": str(job.get("provider") or ""),
        "outcome": "error",
        "reason_code": reason_code,
        "skipped": None,
    }


def _jobs_from_payload(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("providers")
    if not isinstance(raw, list):
        return []
    jobs: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        provider = str(item.get("provider") or "").strip()
        if not provider:
            continue
        jobs.append(dict(item))
    return jobs


def _positive_int(value: object, default: int) -> int:
    if type(value) is int and value > 0:
        return value
    return default


def _positive_float(value: object, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    number = float(value)
    if number != number or number <= 0.0:
        return default
    return number


if __name__ == "__main__":
    raise SystemExit(main())
