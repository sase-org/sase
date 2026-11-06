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

        from sase.core.atomic_json import write_json_marker_atomic

        payload = {
            "schema_version": 1,
            "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "provider": execution_provider_label,
            "error": error_content[:4000],
        }
        write_json_marker_atomic(
            Path(artifacts_dir) / ".sase_provider_failure.json", payload
        )
    except Exception:  # noqa: BLE001 - failure recording never masks the error.
        logger.debug("provider-failure recording failed", exc_info=True)


def _persist_partial_staged_response(
    artifacts_dir: str | None,
    error_content: str,
    execution_provider_label: str,
) -> None:
    """Persist a best-effort staged response after a provider failure.

    Best effort and never raises: a missing stage, an already-persisted real
    response, or any write error simply leaves adoption to the failure-record
    fallback. The synthesized reply cites the failure record and is marked
    partial so the follow-up prompt says the starter's last reply is
    incomplete.
    """
    if not artifacts_dir:
        return
    try:
        from sase.agent.staged_handoff import (
            read_staged_handoff,
            read_staged_handoff_response,
            write_staged_handoff_response,
        )
    except Exception:  # noqa: BLE001 - failure handling fails open to retry.
        return
    try:
        staged = read_staged_handoff(artifacts_dir)
        if staged is None:
            return
        staged_id = str(staged.get("staged_id") or "")
        if not staged_id:
            return
        if (
            read_staged_handoff_response(staged_id, artifacts_dir=artifacts_dir)
            is not None
        ):
            return
        detail = error_content.strip()[:2000] or "(no error detail)"
        partial_reply = (
            "[Partial staged reply: the provider "
            f"{execution_provider_label!r} failed after a valid stage. "
            "The starter's last reply is incomplete; continue from the staged "
            f"state, not from a complete answer. Provider error: {detail}]"
        )
        write_staged_handoff_response(
            staged_id, partial_reply, artifacts_dir=artifacts_dir, partial=True
        )
    except Exception:  # noqa: BLE001 - partial persistence never masks the error.
        logger.debug("partial staged-response recording failed", exc_info=True)


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
    _persist_partial_staged_response(
        artifacts_dir, error_content, execution_provider_label
    )
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
