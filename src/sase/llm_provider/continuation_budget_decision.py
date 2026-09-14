"""Decision normalization, post-projection verification, and refusal messages."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.llm_provider.continuation_budget_projection import utf8_len


def normalized_decision(decision: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(decision)
    if "target_prompt_bytes" not in normalized:
        normalized["target_prompt_bytes"] = normalized.get("prompt_budget_bytes")
    if normalized.get("kind") == "refuse":
        normalized.setdefault("disposition", "context_budget_exceeded")
        if not normalized.get("recovery_guidance"):
            normalized["recovery_guidance"] = [
                "Resume with an adequate explicit checkpoint or choose a route "
                "with a larger context budget.",
                "Do not rerun the monitored command solely to rebuild context.",
            ]
    return normalized


def verify_projection(
    decision: Mapping[str, Any],
    projected_prompt: str,
) -> dict[str, Any]:
    """Remeasure actual projected UTF-8 bytes; refuse durably if still oversized.

    Rust selects reductions from declared candidate byte counts computed
    before projection. Applying those reductions can save fewer bytes than
    declared (defensive overlap skipping, for example), so the prompt that
    would actually be sent must be remeasured here -- never trust the
    pre-projection estimate as proof the compacted prompt fits.
    """

    if str(decision.get("kind") or "") != "compact":
        return dict(decision)
    projected_bytes = utf8_len(projected_prompt)
    target = _intish(
        decision.get("target_prompt_bytes") or decision.get("prompt_budget_bytes")
    )
    updated = dict(decision)
    updated["estimated_prompt_bytes"] = projected_bytes
    if projected_bytes <= target:
        return updated
    updated["kind"] = "refuse"
    updated["reasons"] = [
        *_strings(updated.get("reasons")),
        "post_projection_budget_exceeded",
    ]
    return normalized_decision(updated)


def refusal_message(decision: Mapping[str, Any]) -> str:
    estimated = _intish(decision.get("estimated_prompt_bytes"))
    target = _intish(
        decision.get("target_prompt_bytes") or decision.get("prompt_budget_bytes")
    )
    reasons = ", ".join(_strings(decision.get("reasons"))) or "context_budget_exceeded"
    guidance = "; ".join(_strings(decision.get("recovery_guidance")))
    if not guidance:
        guidance = (
            "Resume with an adequate checkpoint or choose a route with a larger "
            "context budget; do not rerun the monitored command just to rebuild "
            "context."
        )
    return (
        "Continuation context budget exceeded: final expanded prompt is "
        f"{estimated} bytes, budget target is {target} bytes "
        f"({reasons}). {guidance}"
    )


def _intish(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except ValueError:
        return 0


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]
