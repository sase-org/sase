"""Configuration for the Agent CLIs update-history panel."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sase.config.core import load_merged_config


@dataclass(frozen=True)
class AgentCliHistoryConfig:
    """Config for the Agent CLIs update-history panel."""

    enabled: bool = True
    max_rows: int = 8


def load_agent_cli_history_config(
    load_fn: Callable[[], dict[str, Any]] = load_merged_config,
) -> AgentCliHistoryConfig:
    """Load ``ace.updates.agent_cli_history[_max_rows]``, defaults on any error."""
    try:
        data = load_fn()
    except Exception:  # noqa: BLE001 - config failures should not break the pane.
        return AgentCliHistoryConfig()
    ace = data.get("ace") if isinstance(data, dict) else None
    updates = ace.get("updates") if isinstance(ace, dict) else None
    if not isinstance(updates, dict):
        return AgentCliHistoryConfig()
    return AgentCliHistoryConfig(
        enabled=_coerce_bool(updates.get("agent_cli_history"), default=True),
        max_rows=_coerce_nonnegative_int(
            updates.get("agent_cli_history_max_rows"),
            default=8,
        ),
    )


def _coerce_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", "none", "disabled"}:
            return False
    return default


def _coerce_nonnegative_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value if value >= 0 else default
    if isinstance(value, float) and value.is_integer():
        return int(value) if value >= 0 else default
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return default
        return parsed if parsed >= 0 else default
    return default
