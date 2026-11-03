"""Typed ``agent_hijack`` config access and alias-candidate assembly.

The ladder is an ordered list of ``@alias`` rungs (``["@large", "@xlarge"]``
by default). ``successor_context`` is ``fork`` (inline the transcript via
``#fork:``, the default) or ``brief`` (evidence brief plus transcript path).
Unknown rung names fall back to the defaults with a warning so a typo never
silently flattens the escalation walk.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from collections.abc import Mapping

LOG = logging.getLogger(__name__)

DEFAULT_ESCALATION_LADDER: tuple[str, ...] = ("@large", "@xlarge")
DEFAULT_SUCCESSOR_CONTEXT = "fork"
VALID_SUCCESSOR_CONTEXTS = frozenset({"fork", "brief"})


@dataclass(frozen=True)
class AgentHijackConfig:
    """Validated ``agent_hijack`` config section."""

    escalation_ladder: tuple[str, ...] = DEFAULT_ESCALATION_LADDER
    successor_context: str = DEFAULT_SUCCESSOR_CONTEXT


def _merged_config() -> dict[str, Any]:
    try:
        from sase.config import load_merged_config

        data = load_merged_config()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _known_alias_names() -> set[str]:
    try:
        from sase.llm_provider.config import model_alias_names

        return set(model_alias_names())
    except Exception:
        return set()


def agent_hijack_config() -> AgentHijackConfig:
    """Return the validated ``agent_hijack`` config section.

    Unknown rung names and unknown ``successor_context`` values fall back to
    the defaults with a warning; an empty or malformed ladder also falls back.
    """
    raw = _merged_config().get("agent_hijack", {})
    if not isinstance(raw, dict):
        raw = {}

    ladder_raw = raw.get("escalation_ladder", list(DEFAULT_ESCALATION_LADDER))
    successor_raw = raw.get("successor_context", DEFAULT_SUCCESSOR_CONTEXT)

    known = _known_alias_names()
    ladder: list[str] = []
    if isinstance(ladder_raw, list) and ladder_raw:
        seen: set[str] = set()
        for entry in ladder_raw:
            if not isinstance(entry, str) or not entry.strip():
                continue
            rung = entry.strip()
            if not rung.startswith("@"):
                rung = f"@{rung}"
            if rung in seen:
                continue
            seen.add(rung)
            bare = rung[1:]
            if known and bare not in known:
                LOG.warning(
                    "agent_hijack.escalation_ladder: unknown alias %r; "
                    "falling back to defaults",
                    rung,
                )
                ladder = []
                break
            ladder.append(rung)
    if not ladder:
        if isinstance(ladder_raw, list) and ladder_raw:
            LOG.warning(
                "agent_hijack.escalation_ladder is invalid; falling back to defaults",
            )
        ladder = list(DEFAULT_ESCALATION_LADDER)

    if successor_raw in VALID_SUCCESSOR_CONTEXTS:
        successor = str(successor_raw)
    else:
        if successor_raw != DEFAULT_SUCCESSOR_CONTEXT:
            LOG.warning(
                "agent_hijack.successor_context %r is invalid; falling back to %r",
                successor_raw,
                DEFAULT_SUCCESSOR_CONTEXT,
            )
        successor = DEFAULT_SUCCESSOR_CONTEXT

    return AgentHijackConfig(
        escalation_ladder=tuple(ladder),
        successor_context=successor,
    )


def build_alias_candidates(
    ladder: tuple[str, ...] | list[str] | None = None,
    *,
    provider_disables: Mapping[str, Any] | None = None,
) -> dict[str, list[str]]:
    """Build ordered, availability-filtered candidates per ladder rung.

    Each rung maps to the alias's currently available concrete targets in
    display order (provider disables honoured). Non-selector aliases resolve
    to their single target when it is available.
    """
    if ladder is None:
        ladder = agent_hijack_config().escalation_ladder
    candidates: dict[str, list[str]] = {}
    for rung in ladder:
        rung_str = rung.strip() if isinstance(rung, str) else ""
        if not rung_str:
            continue
        if not rung_str.startswith("@"):
            rung_str = f"@{rung_str}"
        bare = rung_str[1:]
        targets = _candidates_for_alias(bare, provider_disables)
        candidates[rung_str] = targets
    return candidates


def _candidates_for_alias(
    bare: str,
    provider_disables: Mapping[str, Any] | None,
) -> list[str]:
    try:
        from sase.llm_provider.model_alias_resolution_selector import (
            model_alias_selector_details,
        )
    except Exception:
        model_alias_selector_details = None  # type: ignore[assignment]
    if model_alias_selector_details is not None:
        try:
            details = model_alias_selector_details(
                bare,
                provider_disables=provider_disables,  # type: ignore[arg-type]
            )
        except Exception:
            details = None
        if details is not None:
            out: list[str] = []
            for m in details.members:
                if (
                    not getattr(m, "available", False)
                    or not getattr(m, "valid", True)
                    or not getattr(m, "target", None)
                ):
                    continue
                target = str(m.target)
                effort = getattr(m, "effort", None)
                if effort:
                    target = f"{target}@{effort}"
                out.append(target)
            return out
    try:
        from sase.llm_provider.config import resolve_model_alias
        from sase.llm_provider.model_alias_resolution_types import (
            resolved_target_is_available,
        )

        target = resolve_model_alias(
            f"@{bare}",
            provider_disables=provider_disables,  # type: ignore[arg-type]
        )
    except Exception:
        return []
    if not target:
        return []
    try:
        if not resolved_target_is_available(
            target,
            provider_disables=provider_disables,  # type: ignore[arg-type]
        ):
            return []
    except Exception:
        pass
    return [str(target)]


__all__ = [
    "AgentHijackConfig",
    "DEFAULT_ESCALATION_LADDER",
    "DEFAULT_SUCCESSOR_CONTEXT",
    "VALID_SUCCESSOR_CONTEXTS",
    "agent_hijack_config",
    "build_alias_candidates",
]
