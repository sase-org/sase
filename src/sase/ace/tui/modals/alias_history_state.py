"""Immutable request/state types for the Launch Control alias-history panel.

Keeps :class:`~sase.ace.tui.modals.alias_history_modal.AliasHistoryModal` free
of mutable Launch Control rows: a :class:`AliasHistoryEntryRequest` snapshots
everything the panel knew about the entry row at ``H``-press time, and a
:class:`AliasHistoryLoadRequest` is the immutable query the modal re-issues on
every initial load or re-query action.
"""

from __future__ import annotations

from dataclasses import dataclass

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


def doubled_alias_history_limit(current_limit: int) -> int:
    """Return the next ``Ctrl+K`` limit — at least one more than *current_limit*."""
    return max(current_limit + 1, current_limit * 2)


__all__ = [
    "AliasHistoryEntryRequest",
    "AliasHistoryLoadRequest",
    "alias_history_run_key",
    "doubled_alias_history_limit",
    "initial_alias_history_load_request",
]
