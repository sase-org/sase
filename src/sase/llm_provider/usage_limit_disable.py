"""Runtime enforcement: detect usage-limit failures and disable the provider.

Called from the LLM invocation error paths in :mod:`sase.llm_provider._invoke`
and again from :func:`sase.axe.run_agent_exec_retry.handle_workflow_error` as a
backstop when the provider's retry patterns do not match. Writes go through the
existing Rust-backed :mod:`sase.llm_provider.provider_disable` store — this
module is the only writer that uses ``source="usage_limit"``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import time

from sase.telemetry.metrics import LLM_PROVIDER_AUTO_DISABLES

from .provider_disable import (
    ProviderDisableWriteOutcome,
    try_disable_provider,
    try_disable_provider_until,
)
from .usage_limit_config import (
    UsageLimitDetection,
    UsageLimitSettings,
    detect_usage_limit,
    get_usage_limit_settings,
)

logger = logging.getLogger(__name__)

USAGE_LIMIT_DISABLE_SOURCE = "usage_limit"

# Generous: draining sequentially relaunches up to relaunch_limit agents
# through the same restart machinery a human `sase agent restart` uses,
# each involving a kill and a fresh launch.
_DRAIN_PROC_TIMEOUT_SECONDS = 1800


def handle_possible_usage_limit(
    *,
    provider: str,
    error_text: str,
    model: str | None = None,
    artifacts_dir: str | None = None,
) -> UsageLimitDetection | None:
    """Detect a usage-limit failure and write a temporary provider disable.

    Never raises: a bug in pattern matching, reset parsing, or disable
    writing must never replace or mask the provider error the caller is
    already propagating.

    Returns the ``UsageLimitDetection`` when the error matched (whether or
    not this caller won the first-writer disable window — an already-active
    disable is left untouched), or ``None`` when there was no match or
    detection failed.
    """
    try:
        return _handle_possible_usage_limit(
            provider=provider,
            error_text=error_text,
            model=model,
            artifacts_dir=artifacts_dir,
        )
    except Exception:
        logger.warning(
            "usage-limit detection failed for provider %r", provider, exc_info=True
        )
        return None


def _handle_possible_usage_limit(
    *,
    provider: str,
    error_text: str,
    model: str | None,
    artifacts_dir: str | None,
) -> UsageLimitDetection | None:
    now = time.time()
    detection = detect_usage_limit(provider, error_text, now=now)
    if detection is None:
        return None

    if detection.expires_at is not None:
        outcome = try_disable_provider_until(
            provider,
            detection.expires_at,
            source=USAGE_LIMIT_DISABLE_SOURCE,
            now=now,
        )
    else:
        outcome = try_disable_provider(
            provider,
            detection.disable_seconds,
            source=USAGE_LIMIT_DISABLE_SOURCE,
            now=now,
        )

    if not outcome.inserted:
        # Many agents can hit the same provider limit within the same
        # minute; the first writer wins the window and the rest are
        # silent, so as not to extend the disable or double-notify.
        logger.debug(
            "usage-limit disable already active for provider %r; skipping write "
            "(model=%r, artifacts_dir=%r)",
            provider,
            model,
            artifacts_dir,
        )
        return detection

    LLM_PROVIDER_AUTO_DISABLES.labels(provider=provider).inc()
    logger.info(
        "auto-disabled LLM provider %r for %.0fs after usage-limit match "
        "(pattern=%r, used_reset_hint=%s, model=%r, artifacts_dir=%r)",
        provider,
        detection.disable_seconds,
        detection.matched_pattern,
        detection.used_reset_hint,
        model,
        artifacts_dir,
    )

    settings = get_usage_limit_settings()
    if settings.notify:
        _dispatch_disable_followup(
            detection, settings, outcome, model=model, artifacts_dir=artifacts_dir
        )

    return detection


def _dispatch_disable_followup(
    detection: UsageLimitDetection,
    settings: UsageLimitSettings,
    outcome: ProviderDisableWriteOutcome,
    *,
    model: str | None,
    artifacts_dir: str | None,
) -> None:
    """Own the one notification for this disable: inline, or via a drain.

    A drain is only attempted when the flag is on, ``relaunch`` is enabled,
    and the record this call just won is a hard disable -- a soft disable
    spares the provider in pools but still allows launches, so nothing is
    stranded. When a drain is submitted it owns the (enriched) notification;
    this process sends none. A submission failure falls back to today's
    inline notification so the user is never left silent.
    """
    if not (settings.relaunch and outcome.record.is_hard and _provider_drain_enabled()):
        _notify_usage_limit_disabled(
            detection, model=model, artifacts_dir=artifacts_dir
        )
        return
    if _submit_drain(detection, settings, model=model, artifacts_dir=artifacts_dir):
        return
    _notify_usage_limit_disabled(detection, model=model, artifacts_dir=artifacts_dir)


def _provider_drain_enabled() -> bool:
    from sase.feature_flags import FeatureFlag, current_flags

    return current_flags().enabled(FeatureFlag.provider_drain)


def _notify_usage_limit_disabled(
    detection: UsageLimitDetection,
    *,
    model: str | None,
    artifacts_dir: str | None,
) -> None:
    # Isolated from the caller's exception handling: a notification bug must
    # never mask the disable write that already succeeded above.
    try:
        from sase.notifications.senders import notify_provider_usage_limit_disabled

        notify_provider_usage_limit_disabled(
            detection,
            agent_name=_agent_name_from_artifacts_dir(artifacts_dir),
            model=model,
        )
    except Exception:
        logger.warning(
            "usage-limit notification failed for provider %r",
            detection.provider,
            exc_info=True,
        )


def _submit_drain(
    detection: UsageLimitDetection,
    settings: UsageLimitSettings,
    *,
    model: str | None,
    artifacts_dir: str | None,
) -> bool:
    """Submit a durable drain proc that owns the enriched notification.

    Returns True once submission succeeds (the drain proc now owns
    notifying), False when submission itself raised.
    """
    try:
        from sase.ops.names import AGENT_DRAIN
        from sase.procs import ProcSubmitRequest, submit_proc_request

        provider = detection.provider
        argv = [
            "sase",
            "agent",
            "drain",
            provider,
            "--yes",
            "--json",
            "--limit",
            str(settings.relaunch_limit),
        ]
        payload = {
            "notify": True,
            "provider": provider,
            "matched_pattern": detection.matched_pattern,
            "raw_message": detection.raw_message,
            "disable_seconds": detection.disable_seconds,
            "expires_at": detection.expires_at,
            "used_reset_hint": detection.used_reset_hint,
            "trigger_agent": _agent_name_from_artifacts_dir(artifacts_dir),
            "trigger_model": model,
        }
        submit_proc_request(
            ProcSubmitRequest(
                argv=argv,
                label=f"Drain {provider.upper()} (usage limit)",
                cwd=str(Path.home()),
                origin=USAGE_LIMIT_DISABLE_SOURCE,
                operation=AGENT_DRAIN,
                operation_payload=payload,
                tags=["llm", "usage-limit", provider],
                concurrency_keys=[f"provider-drain:{provider}"],
                timeout_seconds=_DRAIN_PROC_TIMEOUT_SECONDS,
            )
        )
        return True
    except Exception:
        logger.warning(
            "provider-drain submission failed for %r; falling back to the "
            "inline usage-limit notification",
            detection.provider,
            exc_info=True,
        )
        return False


def _agent_name_from_artifacts_dir(artifacts_dir: str | None) -> str | None:
    """Best-effort agent identity for the notification, read from agent_meta.json."""
    if not artifacts_dir:
        return None
    try:
        data = json.loads(
            (Path(artifacts_dir) / "agent_meta.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    name = data.get("name")
    return name if isinstance(name, str) and name else None


__all__ = [
    "USAGE_LIMIT_DISABLE_SOURCE",
    "handle_possible_usage_limit",
]
