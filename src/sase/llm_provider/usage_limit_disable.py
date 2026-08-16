"""Runtime enforcement: detect usage-limit failures and disable the provider.

Called from the LLM invocation error paths in :mod:`sase.llm_provider._invoke`.
Writes go through the existing Rust-backed :mod:`sase.llm_provider.provider_disable`
store — this module is the only writer that uses ``source="usage_limit"``.
"""

from __future__ import annotations

import logging

from sase.telemetry.metrics import LLM_PROVIDER_AUTO_DISABLES

from .provider_disable import (
    disable_provider,
    disable_provider_until,
    get_active_provider_disable,
)
from .usage_limit_config import UsageLimitDetection, detect_usage_limit

logger = logging.getLogger(__name__)

USAGE_LIMIT_DISABLE_SOURCE = "usage_limit"


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
    not a disable was actually written — an already-active disable is left
    untouched), or ``None`` when there was no match or detection failed.
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
    detection = detect_usage_limit(provider, error_text)
    if detection is None:
        return None

    if get_active_provider_disable(provider) is not None:
        # Many agents can hit the same provider limit within the same
        # minute; the first one to arrive here wins and the rest are
        # silent, so as not to extend the disable or double-notify.
        logger.debug(
            "usage-limit disable already active for provider %r; skipping write "
            "(model=%r, artifacts_dir=%r)",
            provider,
            model,
            artifacts_dir,
        )
        return detection

    if detection.expires_at is not None:
        disable_provider_until(
            provider,
            detection.expires_at,
            source=USAGE_LIMIT_DISABLE_SOURCE,
        )
    else:
        disable_provider(
            provider,
            detection.disable_seconds,
            source=USAGE_LIMIT_DISABLE_SOURCE,
        )

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

    return detection


__all__ = [
    "USAGE_LIMIT_DISABLE_SOURCE",
    "handle_possible_usage_limit",
]
