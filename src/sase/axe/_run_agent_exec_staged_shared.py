"""Shared types and helpers for staged-handoff adoption.

Public names in this private module are shared by the staged split
(``run_agent_exec_staged_*``). Helpers needed by only one staged module
live in that module instead.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.agent.staged_handoff import StagedHandoffError

if TYPE_CHECKING:
    from sase.axe.run_agent_exec_types import AgentExecContext, LoopState


@dataclass(frozen=True)
class StagedInlineContinuation:
    """Runner-only state needed to continue a plan inline after adoption."""

    ctx: AgentExecContext
    state: LoopState


@dataclass(frozen=True)
class StagedAdoptionOutcome:
    """Narrow adopter result carrying an explicit custodian identity.

    ``outcome`` preserves the legacy ``str | None`` loop-outcome semantics
    (``None`` continues inline). ``custodian`` is the actual successor
    artifacts identity that now owns carried work, when the adopter knows
    it. When ``None``, dispatch derives the custodian from continuation
    state (successor/gate dirs), never from command text. ``refs`` are
    merged into the adoption receipt as stable kind-specific identities.
    """

    outcome: str | None = None
    custodian: str | None = None
    refs: Mapping[str, Any] | None = None


StagedAdopter = Callable[
    [Mapping[str, Any], Mapping[str, Any], StagedInlineContinuation, str],
    str | None | StagedAdoptionOutcome,
]


def read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StagedHandoffError(f"malformed {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise StagedHandoffError(f"malformed {label}: not a JSON object")
    return payload


def proven_ids_for_settlement(
    result_payload: Mapping[str, Any],
    current_context: Any,
    staged_id: str,
) -> frozenset[str]:
    """Return dirty ids with current carry/prepared proof for *staged_id*."""
    from sase.finalizers.commit_carry import proven_coverage_ids_from_result_payload

    digest_by_id = {
        obligation.obligation_id: obligation.digest or ""
        for obligation in getattr(current_context, "obligations", ())
        if getattr(obligation, "kind", "") == "repository"
    }
    try:
        return proven_coverage_ids_from_result_payload(
            result_payload,
            digest_by_id=digest_by_id,
            staged_ref=staged_id,
        )
    except Exception:
        return frozenset()


__all__ = [
    "StagedAdopter",
    "StagedAdoptionOutcome",
    "StagedInlineContinuation",
    "proven_ids_for_settlement",
    "read_json_object",
]
