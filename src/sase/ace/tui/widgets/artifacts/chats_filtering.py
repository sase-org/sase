"""In-memory filtering for the Artifacts Chats catalog snapshot."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from sase.history.chat_catalog_provenance import ChatCatalogEntry
from sase.history.chat_filter_query import ChatFilterValues

from .chats_data import ChatsSnapshot


def filter_chats_snapshot(
    snapshot: ChatsSnapshot | None,
    values: ChatFilterValues,
) -> ChatsSnapshot | None:
    """Return a view whose entries match *values*, preserving summary totals."""

    if snapshot is None or values.is_empty:
        return snapshot
    entries = tuple(entry for entry in snapshot.entries if _chat_matches(entry, values))
    return replace(snapshot, catalog=replace(snapshot.catalog, entries=entries))


def _chat_matches(entry: ChatCatalogEntry, values: ChatFilterValues) -> bool:
    """Match one catalog row without touching disk."""

    if values.provenances and entry.provenance not in values.provenances:
        return False
    if values.machines and not _matches_any(entry.source_machine, values.machines):
        return False
    if values.projects and not _matches_any(entry.project_key, values.projects):
        return False
    agent_values = tuple(
        value
        for value in (
            entry.agent,
            entry.agent_local_name,
            entry.agent_global_name,
        )
        if value
    )
    if values.agents and not _tuple_matches_any(agent_values, values.agents):
        return False
    if values.workflows and not _matches_any(entry.workflow, values.workflows):
        return False

    timestamp = _entry_epoch(entry)
    if values.since is not None and (timestamp is None or timestamp < values.since):
        return False
    if values.until is not None and (timestamp is None or timestamp > values.until):
        return False

    haystack = " ".join(
        value
        for value in (
            entry.basename,
            entry.agent,
            entry.agent_local_name,
            entry.agent_global_name,
            entry.workflow,
            entry.prompt_snippet,
            entry.response_snippet,
        )
        if value
    ).casefold()
    return all(term.casefold() in haystack for term in values.text)


def _matches_any(value: str | None, needles: tuple[str, ...]) -> bool:
    if value is None:
        return False
    folded = value.casefold()
    return any(folded == needle.casefold() for needle in needles)


def _tuple_matches_any(values: tuple[str, ...], needles: tuple[str, ...]) -> bool:
    folded = {value.casefold() for value in values}
    return any(needle.casefold() in folded for needle in needles)


def _entry_epoch(entry: ChatCatalogEntry) -> int | None:
    try:
        return int(datetime.fromisoformat(entry.mtime).timestamp())
    except ValueError:
        return None


__all__ = ["filter_chats_snapshot"]
