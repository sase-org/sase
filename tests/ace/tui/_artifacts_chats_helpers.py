"""Shared provenance catalog fixtures for Artifacts Chats tests."""

from __future__ import annotations

from dataclasses import replace

from sase.ace.tui.widgets.artifacts.chats_data import ChatsSnapshot
from sase.history.chat_catalog_provenance import (
    ChatCatalogEntry,
    ChatCatalogSnapshot,
    ChatProvenance,
)


def chat_entry(
    name: str,
    *,
    provenance: ChatProvenance = "local",
    mtime: str = "2026-07-24T14:32:00-04:00",
    machine: str | None = None,
) -> ChatCatalogEntry:
    return ChatCatalogEntry(
        path=f"~/.sase/chats/202607/{name}.md",
        absolute_path=f"/tmp/chats/{name}.md",
        basename=name,
        mtime=mtime,
        size_bytes=1024,
        workflow="code",
        agent=f"sase.{name}--code",
        timestamp="260724_143200",
        prompt_snippet=f"Prompt for {name}",
        response_snippet=f"Response for {name}",
        provenance=provenance,
        source_machine=machine,
        source_username="bryan" if machine else None,
        project_key="alpha",
        agent_artifact_dir=f"/tmp/artifacts/{name}",
        agent_local_name=f"sase.{name}--code",
        agent_global_name=f"bryan@athena:sase.{name}--code",
        sidecar_repo="/tmp/agents",
        sidecar_relpath=f"agents/{name}/chat.md",
        publication_pending=False,
        publication_last_error=None,
        publication_quarantined=False,
    )


def catalog(
    entries: tuple[ChatCatalogEntry, ...],
    *,
    truncated: bool = False,
) -> ChatCatalogSnapshot:
    counts: dict[ChatProvenance, int] = {
        provenance: sum(entry.provenance == provenance for entry in entries)
        for provenance in ("local", "shared", "remote", "unknown")
    }
    return ChatCatalogSnapshot(
        entries=entries,
        provenance_counts=counts,
        remote_machines=frozenset(
            entry.source_machine
            for entry in entries
            if entry.provenance == "remote" and entry.source_machine is not None
        ),
        truncated=truncated,
    )


def pane_snapshot(
    entries: tuple[ChatCatalogEntry, ...],
    *,
    project: str | None = "alpha",
    complete: bool = True,
) -> ChatsSnapshot:
    return ChatsSnapshot(
        project=project,
        catalog=catalog(entries, truncated=not complete),
        complete=complete,
    )


def with_mtime(entry: ChatCatalogEntry, mtime: str) -> ChatCatalogEntry:
    return replace(entry, mtime=mtime)


__all__ = ["catalog", "chat_entry", "pane_snapshot", "with_mtime"]
