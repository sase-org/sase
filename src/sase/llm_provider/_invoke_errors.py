"""Staged-finalization handling for ordinary provider failures."""

from __future__ import annotations

import logging
from typing import Any

from .types import InvokeResult, ModelTier

logger = logging.getLogger(__name__)


def _staged_present_for_provider_failure(artifacts_dir: str | None) -> bool:
    """Return whether staged handoff state governs a provider failure."""
    if not artifacts_dir:
        return False
    try:
        from sase.agent.staged_handoff import StagedHandoffError, read_staged_handoff
    except Exception:  # noqa: BLE001 - failure detection fails open to retry.
        return False
    try:
        return read_staged_handoff(artifacts_dir) is not None
    except StagedHandoffError:
        return True
    except Exception:  # noqa: BLE001 - failure detection fails open to retry.
        return False


def _record_provider_failure(
    artifacts_dir: str | None,
    error_content: str,
    execution_provider_label: str,
) -> None:
    """Persist provider-failure evidence for the staged completion controller."""
    if not artifacts_dir:
        return
    try:
        from datetime import UTC, datetime
        from pathlib import Path

        from sase.agent.gate_intent import atomic_write_json

        payload = {
            "schema_version": 1,
            "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "provider": execution_provider_label,
            "error": error_content[:4000],
        }
        atomic_write_json(Path(artifacts_dir) / ".sase_provider_failure.json", payload)
    except Exception:  # noqa: BLE001 - failure recording never masks the error.
        logger.debug("provider-failure recording failed", exc_info=True)


def finalize_staged_after_provider_error(
    *,
    provider: Any,
    query: str,
    error_content: str,
    model_tier: ModelTier,
    suppress_output: bool,
    model_override: str | None,
    artifacts_dir: str | None,
    options: Any,
    execution_provider_label: str,
) -> None:
    """Run staged finalizers after failure without masking the provider error."""
    if not artifacts_dir:
        return
    try:
        from sase.finalizers.owned_turn import finalizer_owned_turn_is_active
    except Exception:  # noqa: BLE001 - fail open to raising the original error.
        return
    if finalizer_owned_turn_is_active():
        return
    if not _staged_present_for_provider_failure(artifacts_dir):
        return
    _record_provider_failure(artifacts_dir, error_content, execution_provider_label)
    try:
        from sase.finalizers import run_finalizers

        failure_result = InvokeResult(content=error_content, usage=None)
        run_finalizers(
            provider=provider,
            original_prompt=query,
            invoke_result=failure_result,
            model_tier=model_tier,
            suppress_output=suppress_output,
            model_override=model_override,
            artifacts_dir=artifacts_dir,
            options=options,
        )
    except Exception:  # noqa: BLE001 - original provider error always wins.
        logger.debug(
            "staged finalization after provider failure did not settle",
            exc_info=True,
        )
