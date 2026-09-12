"""Shared durable subscription-usage refresh submit/join service."""

from __future__ import annotations

import logging
import os
import re
import shutil
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home
from sase.llm_provider.usage.config import (
    collection_skip_reason,
    get_usage_metrics_settings,
)
from sase.llm_provider.usage.store import (
    PROVIDER_USAGE_REFRESH_DEFERRED,
    PROVIDER_USAGE_REFRESH_JOINED,
    PROVIDER_USAGE_REFRESH_RESERVED,
    admit_provider_usage_refresh,
    evaluate_provider_usage_refresh_due,
    mark_provider_usage_refresh_due,
    prepare_provider_usage_account_context,
    release_provider_usage_refresh,
)

log = logging.getLogger(__name__)

USAGE_REFRESH_OPERATION = "usage.refresh"
USAGE_REFRESH_RECEIPT_SCHEMA_VERSION = 1
MAX_CONCURRENT_USAGE_PROBES = 3
USAGE_REFRESH_PROVIDER_DEADLINE_SECONDS = 10.0
USAGE_REFRESH_BATCH_DEADLINE_SECONDS = 30.0
USAGE_REFRESH_LEASE_TTL_SECONDS = 45.0
USAGE_REFRESH_CONTEXT_ID = "default"
USAGE_REFRESH_ORIGINS = ("ace", "axe", "cli", "limit_event")

_RUNNER_MODULE = "sase.llm_provider.usage.refresh_runner"


@dataclass(frozen=True)
class _UsageRefreshProviderResult:
    """One provider's place in a batch receipt."""

    provider: str
    status: str
    reason: str | None
    operation_id: str | None
    lease_id: str | None = None
    context_id: str = USAGE_REFRESH_CONTEXT_ID
    account_generation: int = 1

    def to_json(self) -> dict[str, Any]:
        """Return a JSON-ready mapping."""
        return {
            "account_generation": self.account_generation,
            "context_id": self.context_id,
            "lease_id": self.lease_id,
            "operation_id": self.operation_id,
            "provider": self.provider,
            "reason": self.reason,
            "status": self.status,
        }


@dataclass(frozen=True)
class UsageRefreshReceipt:
    """Batch receipt covering every requested provider."""

    schema_version: int
    origin: str
    operation_ids: tuple[str, ...]
    providers: tuple[_UsageRefreshProviderResult, ...]

    def to_json(self) -> dict[str, Any]:
        """Return a JSON-ready mapping."""
        return {
            "operation_ids": list(self.operation_ids),
            "origin": self.origin,
            "providers": [item.to_json() for item in self.providers],
            "schema_version": self.schema_version,
        }

    @property
    def started(self) -> bool:
        """Return whether this receipt started or joined any durable work."""
        return bool(self.operation_ids)


def request_due_usage_refresh(
    *,
    origin: str = "axe",
    now: float | None = None,
    plugin_specs: Mapping[str, Mapping[str, Any]] | None = None,
) -> UsageRefreshReceipt:
    """Submit coalesced refresh work for currently due eligible providers."""
    return submit_usage_refresh(
        None,
        explicit=False,
        origin=origin,
        now=now,
        plugin_specs=plugin_specs,
    )


def submit_usage_refresh(
    providers: Sequence[str] | None = None,
    *,
    explicit: bool = False,
    origin: str = "axe",
    now: float | None = None,
    plugin_specs: Mapping[str, Mapping[str, Any]] | None = None,
) -> UsageRefreshReceipt:
    """Admit, join, or defer refresh work for *providers*.

    ``providers is None`` selects background-eligible providers that are due.
    An explicit filter inspects the named providers even when they are not
    background-eligible. Joining one in-flight provider never drops others.
    """
    origin = _normalize_origin(origin)
    from sase.procs import new_proc_id

    settings = get_usage_metrics_settings()
    if not settings.enabled:
        names = tuple(providers or ())
        return _disabled_receipt(names, origin, "config_disabled")

    requested = _resolve_requested_providers(providers)
    if not requested:
        return UsageRefreshReceipt(
            schema_version=USAGE_REFRESH_RECEIPT_SCHEMA_VERSION,
            origin=origin,
            operation_ids=(),
            providers=(),
        )

    results: list[_UsageRefreshProviderResult] = []
    started: list[_UsageRefreshProviderResult] = []
    operation_id = new_proc_id()
    specs = {str(name): dict(spec) for name, spec in (plugin_specs or {}).items()}
    cadence = settings.refresh_seconds

    for provider in requested:
        skip = collection_skip_reason(provider)
        if skip is not None:
            results.append(
                _UsageRefreshProviderResult(
                    provider=provider,
                    status="disabled",
                    reason=skip,
                    operation_id=None,
                )
            )
            continue
        try:
            result = _admit_one(
                provider,
                operation_id=operation_id,
                explicit=explicit,
                cadence_seconds=cadence,
                now=now,
            )
        except Exception:
            log.warning(
                "usage refresh admission failed for %r", provider, exc_info=True
            )
            results.append(
                _UsageRefreshProviderResult(
                    provider=provider,
                    status="error",
                    reason="admission_failed",
                    operation_id=None,
                )
            )
            continue
        results.append(result)
        if result.status == PROVIDER_USAGE_REFRESH_RESERVED:
            started.append(result)

    if started:
        try:
            _submit_started_proc(
                started,
                operation_id=operation_id,
                origin=origin,
                plugin_specs=specs,
                cadence_seconds=cadence,
            )
        except Exception:
            log.warning("usage refresh proc submit failed", exc_info=True)
            _release_started(started, now=now)
            results = [
                (
                    _UsageRefreshProviderResult(
                        provider=item.provider,
                        status="error",
                        reason="submit_failed",
                        operation_id=None,
                        context_id=item.context_id,
                        account_generation=item.account_generation,
                    )
                    if item.status == PROVIDER_USAGE_REFRESH_RESERVED
                    else item
                )
                for item in results
            ]
            started = []

    operation_ids = tuple(
        dict.fromkeys(
            item.operation_id
            for item in results
            if item.operation_id
            and item.status
            in {PROVIDER_USAGE_REFRESH_RESERVED, PROVIDER_USAGE_REFRESH_JOINED}
        )
    )
    return UsageRefreshReceipt(
        schema_version=USAGE_REFRESH_RECEIPT_SCHEMA_VERSION,
        origin=origin,
        operation_ids=operation_ids,
        providers=tuple(results),
    )


def _mark_usage_refresh_due(
    provider: str,
    reason: str,
    *,
    due_at: float | None = None,
    now: float | None = None,
    context_id: str = USAGE_REFRESH_CONTEXT_ID,
) -> None:
    """Mark *provider* due once for *reason*. Never raises to callers."""
    try:
        context = prepare_provider_usage_account_context(provider, context_id, now=now)
        mark_provider_usage_refresh_due(
            provider,
            context.context_id,
            context.account_generation,
            reason,
            due_at=due_at,
            now=now,
        )
    except Exception:
        log.debug("could not mark usage refresh due for %r", provider, exc_info=True)


def trigger_usage_refresh_after_limit_event(
    provider: str,
    *,
    expires_at: float | None = None,
    now: float | None = None,
) -> UsageRefreshReceipt | None:
    """Best-effort due mark and submit after a usage-limit disable."""
    try:
        _mark_usage_refresh_due(provider, "limit_event", now=now)
        if expires_at is not None:
            _mark_usage_refresh_due(
                provider,
                "disable_expiry",
                due_at=expires_at,
                now=now,
            )
        return submit_usage_refresh(
            (provider,),
            explicit=True,
            origin="limit_event",
            now=now,
        )
    except Exception:
        log.debug("usage-limit refresh trigger failed for %r", provider, exc_info=True)
        return None


def eligible_usage_providers(*, include_hidden: bool = False) -> tuple[str, ...]:
    """Return background-eligible registered providers, sorted."""
    from sase.llm_provider.registry import (
        get_llm_metadata_payload,
        model_picker_hidden_provider_names,
        registered_provider_names,
    )

    payload = get_llm_metadata_payload()
    hidden = set() if include_hidden else set(model_picker_hidden_provider_names())
    referenced = _referenced_provider_ids()
    settings = get_usage_metrics_settings()
    eligible: list[str] = []
    for name in registered_provider_names():
        if name in hidden:
            continue
        metadata = payload.get("providers", {}).get(name) or {}
        capabilities = metadata.get("usage_capabilities") or {}
        if capabilities.get("probe") is not True:
            continue
        if not _provider_cli_ready(name, metadata):
            continue
        explicit_enable = settings.providers.get(name) is True
        if name not in referenced and not explicit_enable:
            continue
        if not settings.provider_enabled(name):
            continue
        eligible.append(name)
    return tuple(eligible)


def _resolve_requested_providers(
    providers: Sequence[str] | None,
) -> tuple[str, ...]:
    if providers is None:
        return eligible_usage_providers()
    return tuple(
        dict.fromkeys(str(name).strip() for name in providers if str(name).strip())
    )


def _admit_one(
    provider: str,
    *,
    operation_id: str,
    explicit: bool,
    cadence_seconds: float,
    now: float | None,
) -> _UsageRefreshProviderResult:
    context = prepare_provider_usage_account_context(
        provider, USAGE_REFRESH_CONTEXT_ID, now=now
    )
    if not explicit:
        due = evaluate_provider_usage_refresh_due(
            provider,
            context.context_id,
            context.account_generation,
            cadence_seconds=cadence_seconds,
            explicit=False,
            now=now,
        )
        if not due.due:
            return _UsageRefreshProviderResult(
                provider=provider,
                status=PROVIDER_USAGE_REFRESH_DEFERRED,
                reason=due.reason,
                operation_id=None,
                context_id=context.context_id,
                account_generation=context.account_generation,
            )
    admitted = admit_provider_usage_refresh(
        provider,
        context.context_id,
        context.account_generation,
        operation_id,
        USAGE_REFRESH_LEASE_TTL_SECONDS,
        cadence_seconds=cadence_seconds,
        explicit=explicit,
        now=now,
    )
    reservation = admitted.reservation
    joined_operation = None if reservation is None else reservation.operation_id
    lease_id = None if reservation is None else reservation.lease_id
    status = admitted.status
    result_operation = joined_operation
    if status == PROVIDER_USAGE_REFRESH_DEFERRED:
        result_operation = None
    return _UsageRefreshProviderResult(
        provider=provider,
        status=status,
        reason=admitted.reason,
        operation_id=result_operation,
        lease_id=lease_id,
        context_id=context.context_id,
        account_generation=context.account_generation,
    )


def _submit_started_proc(
    started: Sequence[_UsageRefreshProviderResult],
    *,
    operation_id: str,
    origin: str,
    plugin_specs: Mapping[str, Mapping[str, Any]],
    cadence_seconds: float,
) -> None:
    from sase.procs import ProcSubmitRequest, submit_proc_request

    home = Path(sase_home())
    home.mkdir(parents=True, exist_ok=True)
    payload = {
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
            }
            for item in started
        ],
        "batch_deadline_seconds": USAGE_REFRESH_BATCH_DEADLINE_SECONDS,
    }
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


def _release_started(
    started: Sequence[_UsageRefreshProviderResult], *, now: float | None
) -> None:
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


def _disabled_receipt(
    providers: Sequence[str], origin: str, reason: str
) -> UsageRefreshReceipt:
    results = tuple(
        _UsageRefreshProviderResult(
            provider=name,
            status="disabled",
            reason=reason,
            operation_id=None,
        )
        for name in providers
    )
    return UsageRefreshReceipt(
        schema_version=USAGE_REFRESH_RECEIPT_SCHEMA_VERSION,
        origin=origin,
        operation_ids=(),
        providers=results,
    )


def _normalize_origin(origin: str) -> str:
    cleaned = origin.strip() or "axe"
    if cleaned not in USAGE_REFRESH_ORIGINS:
        return "axe"
    return cleaned


def _referenced_provider_ids() -> set[str]:
    from sase.llm_provider.config import (
        get_big_epic_lander_model,
        get_builtin_model_aliases,
        get_custom_model_aliases,
        get_default_model,
        get_epic_lander_model,
    )
    from sase.llm_provider.model_alias_resolution_types import (
        provider_for_resolved_target,
    )

    targets: list[str] = [
        get_default_model(),
        get_epic_lander_model(),
        get_big_epic_lander_model(),
        *get_builtin_model_aliases().values(),
        *get_custom_model_aliases().values(),
    ]
    names: set[str] = set()
    for target in targets:
        for part in str(target).replace("|", " ").split():
            token = part.split("@", 1)[0].strip()
            if not token:
                continue
            provider = provider_for_resolved_target(token)
            if provider:
                names.add(provider)
    return names


def _provider_cli_ready(provider: str, metadata: Mapping[str, Any]) -> bool:
    if provider == "codex":
        # Match the launcher/collector's own resolver so an NVM-only install
        # (no ``codex`` on PATH) still counts as ready.
        from sase.llm_provider.codex import resolve_codex_executable

        command = resolve_codex_executable()
    else:
        token = re.sub(r"[^A-Za-z0-9]+", "_", provider).strip("_").upper()
        override = os.environ.get(f"SASE_{token}_PATH", "").strip()
        cli_name = metadata.get("autodetect_cli_name")
        command = override or (str(cli_name).strip() if cli_name else "")
    if not command:
        return True
    path = Path(command)
    return path.is_file() or shutil.which(command) is not None


__all__ = [
    "MAX_CONCURRENT_USAGE_PROBES",
    "USAGE_REFRESH_BATCH_DEADLINE_SECONDS",
    "USAGE_REFRESH_CONTEXT_ID",
    "USAGE_REFRESH_LEASE_TTL_SECONDS",
    "USAGE_REFRESH_OPERATION",
    "USAGE_REFRESH_PROVIDER_DEADLINE_SECONDS",
    "USAGE_REFRESH_RECEIPT_SCHEMA_VERSION",
    "UsageRefreshReceipt",
    "eligible_usage_providers",
    "request_due_usage_refresh",
    "submit_usage_refresh",
    "trigger_usage_refresh_after_limit_event",
]
