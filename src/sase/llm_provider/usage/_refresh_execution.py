"""Proc/inline execution for admitted subscription-usage refresh batches.

Store and probe helpers that tests patch on the public
:mod:`sase.llm_provider.usage.refresh` namespace are resolved with late imports
so the facade stays the single patch point.
"""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home
from sase.llm_provider.provider_disable import is_finite_number
from sase.llm_provider.usage._refresh_model import (
    MAX_CONCURRENT_USAGE_PROBES,
    USAGE_INLINE_WAIT_POLL_SECONDS,
    USAGE_REFRESH_BATCH_DEADLINE_SECONDS,
    USAGE_REFRESH_OPERATION,
    USAGE_REFRESH_PROVIDER_DEADLINE_SECONDS,
    UsageRefreshProviderResult,
)

log = logging.getLogger(__name__)

_RUNNER_MODULE = "sase.llm_provider.usage.refresh_runner"


def wait_for_usage_refresh_operations(
    operation_ids: Sequence[str],
    timeout: float,
    *,
    poll_interval: float = USAGE_INLINE_WAIT_POLL_SECONDS,
) -> None:
    """Block until no live store reservation holds any of *operation_ids*.

    Raises TimeoutError when the deadline passes with reservations still live.
    """
    from sase.llm_provider.usage.refresh import (
        list_provider_usage_refresh_reservations,
    )

    pending = {str(item) for item in operation_ids if str(item)}
    if not pending:
        return
    if not is_finite_number(timeout) or float(timeout) < 0.0:
        raise ValueError("timeout must be a finite nonnegative number")
    interval = (
        float(poll_interval)
        if is_finite_number(poll_interval) and float(poll_interval) > 0.0
        else USAGE_INLINE_WAIT_POLL_SECONDS
    )
    deadline = time.monotonic() + float(timeout)
    while True:
        try:
            live = {
                reservation.operation_id
                for reservation in list_provider_usage_refresh_reservations()
                if reservation.operation_id in pending
            }
        except Exception:
            log.debug("usage refresh reservation poll failed", exc_info=True)
            live = set(pending)
        if not live:
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(
                "usage refresh operations still live: " + ", ".join(sorted(live))
            )
        time.sleep(interval)


def _runner_payload(
    started: Sequence[UsageRefreshProviderResult],
    *,
    origin: str,
    plugin_specs: Mapping[str, Mapping[str, Any]],
    cadence_seconds: float,
) -> dict[str, Any]:
    """Build the admitted-batch payload shared by proc and inline runs."""
    from sase.llm_provider.usage.refresh import (
        usage_cli_fingerprint,
        usage_probe_floor,
    )

    return {
        "cadence_seconds": cadence_seconds,
        "max_concurrent": MAX_CONCURRENT_USAGE_PROBES,
        "origin": origin,
        "plugin_specs": {name: dict(spec) for name, spec in plugin_specs.items()},
        "provider_deadline_seconds": USAGE_REFRESH_PROVIDER_DEADLINE_SECONDS,
        "providers": [
            {
                "account_generation": item.account_generation,
                "context_id": item.context_id,
                "lease_id": item.lease_id,
                "plugin_spec": plugin_specs.get(item.provider),
                "provider": item.provider,
                "min_interval_seconds": usage_probe_floor(item.provider),
                "cli_fingerprint": usage_cli_fingerprint(item.provider),
            }
            for item in started
        ],
        "batch_deadline_seconds": USAGE_REFRESH_BATCH_DEADLINE_SECONDS,
    }


def run_inline_batch(
    started: Sequence[UsageRefreshProviderResult],
    *,
    origin: str,
    plugin_specs: Mapping[str, Mapping[str, Any]],
    cadence_seconds: float,
    now: float | None,
) -> list[dict[str, Any]]:
    """Run the admitted batch in-process with the proc runner's payload."""
    from sase.llm_provider.usage.refresh_runner import run_admitted_refresh

    payload = _runner_payload(
        started,
        origin=origin,
        plugin_specs=plugin_specs,
        cadence_seconds=cadence_seconds,
    )
    try:
        return run_admitted_refresh(payload, now=now)
    except Exception:
        log.warning("inline usage refresh failed", exc_info=True)
        crashed = _live_inline_providers(started)
        _record_inline_crash(crashed, cadence_seconds, now=now)
        release_started(crashed, now=now)
        return [
            {
                "provider": item.provider,
                "outcome": "error",
                "reason_code": "probe_failed",
                "skipped": None,
            }
            for item in crashed
        ]


def _live_inline_providers(
    started: Sequence[UsageRefreshProviderResult],
) -> list[UsageRefreshProviderResult]:
    """Return the started providers still holding a live reservation.

    A provider whose probe already recorded and released its lease finished
    before the crash: recording an error for it now would turn its success
    into backoff, and only live reservations are released.
    """
    from sase.llm_provider.usage.refresh import (
        list_provider_usage_refresh_reservations,
    )

    try:
        live = {
            (reservation.operation_id, reservation.provider)
            for reservation in list_provider_usage_refresh_reservations()
        }
    except Exception:
        log.debug("usage refresh reservation read failed", exc_info=True)
        return list(started)
    return [
        item for item in started if (item.operation_id or "", item.provider) in live
    ]


def _record_inline_crash(
    started: Sequence[UsageRefreshProviderResult],
    cadence_seconds: float,
    *,
    now: float | None,
) -> None:
    """Mark crashed inline providers errored when the in-process batch raises."""
    from sase.llm_provider.usage.refresh import (
        record_provider_usage_refresh_attempt,
        usage_cli_fingerprint,
        usage_probe_floor,
    )

    for item in started:
        try:
            record_provider_usage_refresh_attempt(
                item.provider,
                item.context_id,
                item.account_generation,
                "error",
                cadence_seconds=cadence_seconds,
                reason_code="probe_failed",
                min_interval_seconds=usage_probe_floor(item.provider),
                cli_fingerprint=usage_cli_fingerprint(item.provider),
                adaptive=True,
                now=now,
            )
        except Exception:
            log.debug(
                "could not record inline usage refresh crash for %r", item.provider
            )


def submit_started_proc(
    started: Sequence[UsageRefreshProviderResult],
    *,
    operation_id: str,
    origin: str,
    plugin_specs: Mapping[str, Mapping[str, Any]],
    cadence_seconds: float,
) -> None:
    from sase.procs import ProcSubmitRequest, submit_proc_request

    home = Path(sase_home())
    home.mkdir(parents=True, exist_ok=True)
    payload = _runner_payload(
        started,
        origin=origin,
        plugin_specs=plugin_specs,
        cadence_seconds=cadence_seconds,
    )
    submit_proc_request(
        ProcSubmitRequest(
            argv=(sys.executable, "-m", _RUNNER_MODULE),
            label="usage-refresh",
            cwd=home,
            origin=origin,
            proc_id=operation_id,
            operation=USAGE_REFRESH_OPERATION,
            operation_payload=payload,
            concurrency_keys=tuple(
                f"usage-refresh:{item.provider}" for item in started
            ),
            timeout_seconds=int(USAGE_REFRESH_BATCH_DEADLINE_SECONDS) + 15,
            request_fingerprint=f"usage-refresh:{operation_id}",
        )
    )


def release_started(
    started: Sequence[UsageRefreshProviderResult], *, now: float | None
) -> None:
    from sase.llm_provider.usage.refresh import release_provider_usage_refresh

    for item in started:
        if item.lease_id is None:
            continue
        try:
            release_provider_usage_refresh(
                item.provider,
                item.context_id,
                item.account_generation,
                item.lease_id,
                now=now,
            )
        except Exception:
            log.debug("could not release usage refresh lease for %r", item.provider)
