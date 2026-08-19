"""Immutable request/state types for the Launch Control alias-history panel.

Keeps :class:`~sase.ace.tui.modals.alias_history_modal.AliasHistoryModal` free
of mutable Launch Control rows: a :class:`AliasHistoryEntryRequest` snapshots
everything the panel knew about the entry row at ``H``-press time, and a
:class:`AliasHistoryLoadRequest` is the immutable query the modal re-issues on
every initial load or re-query action.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sase.llm_provider.alias_history import AliasHistoryFreshness, AliasHistoryRun
from sase.llm_provider.alias_history_usage import AliasHistoryPoolMember


@dataclass(frozen=True, slots=True)
class AliasHistoryEntryRequest:
    """What a Launch Control row asked history for, snapshotted at ``H``-press time."""

    aliases: tuple[str, ...]
    title_label: str
    is_user_owned: bool
    effective_provider: str | None = None
    effective_model: str | None = None
    effective_effort: str | None = None
    pool: tuple[AliasHistoryPoolMember, ...] = ()

    @property
    def is_single_alias(self) -> bool:
        """Whether this request names exactly one alias (not a bucket)."""
        return len(self.aliases) == 1


@dataclass(frozen=True, slots=True)
class AliasHistoryLoadRequest:
    """One immutable query the modal can issue through ``load_alias_history``."""

    aliases: tuple[str, ...]
    limit_per_alias: int | None
    include_hidden: bool
    freshness: AliasHistoryFreshness


def initial_alias_history_load_request(
    entry: AliasHistoryEntryRequest,
) -> AliasHistoryLoadRequest:
    """Return the first load request for *entry* — config limit, cached."""
    return AliasHistoryLoadRequest(
        aliases=entry.aliases,
        limit_per_alias=None,
        include_hidden=False,
        freshness="cached",
    )


def alias_history_run_key(alias: str, run: AliasHistoryRun) -> str:
    """Return a stable selectable-run key that survives a reload.

    Combining the queried group alias with the run's artifact directory keeps
    the key stable even when the same run appears via more than one alias in
    a bucket group's combined result.
    """
    return f"{alias}:{run.artifact_dir}"


def adjusted_alias_history_limit(
    current_limit: int,
    *,
    initial_limit: int,
    page_size: int,
    direction: Literal["load_more", "unload"],
) -> int:
    """Return the next per-alias limit after a Ctrl+J / Ctrl+K step.

    Load-more adds ``page_size``. Unload subtracts ``page_size`` but never
    drops below the initial ``model_alias_history_limit`` window.
    """
    step = page_size if page_size >= 1 else 1
    if direction == "load_more":
        return current_limit + step
    if direction == "unload":
        return max(initial_limit, current_limit - step)
    raise ValueError(f"unknown alias-history limit direction: {direction!r}")


__all__ = [
    "AliasHistoryEntryRequest",
    "AliasHistoryLoadRequest",
    "adjusted_alias_history_limit",
    "alias_history_run_key",
    "initial_alias_history_load_request",
]
