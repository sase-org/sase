"""Headless chat catalog assembly and provenance classification."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from sase.config import get_agent_owner_identity
from sase.core.machine_hood_facade import (
    machine_qualify_v1_transport_agent_name,
)
from sase.history.chat_catalog import ChatTranscriptInfo

from .artifacts import load_agent_links
from .cache import load_transcript_index, open_catalog_cache
from .models import (
    CHAT_PROVENANCE_VALUES,
    AgentChatLink,
    ChatCatalogEntry,
    ChatCatalogSnapshot,
    ChatProvenance,
    PublicationBacklogItem,
    SidecarAgent,
    SidecarProjectIndex,
)
from .sidecars import load_publication_backlog, load_sidecar_indexes


def load_chat_catalog(
    *,
    limit: int | None = None,
    query: str | None = None,
    provenance: ChatProvenance | None = None,
    machine: str | None = None,
    project: str | None = None,
    force: bool = False,
) -> ChatCatalogSnapshot:
    """Load a newest-first chat catalog without importing any TUI modules."""

    if limit is not None and limit < 0:
        raise ValueError("limit must be non-negative")
    if provenance is not None and provenance not in CHAT_PROVENANCE_VALUES:
        raise ValueError(f"unsupported chat provenance: {provenance}")

    with open_catalog_cache() as cache:
        transcripts = load_transcript_index(cache, force=force)
        agent_links = load_agent_links(cache, force=force)
        sidecars, diagnostics, target_resolution_failed = load_sidecar_indexes(
            cache,
            force=force,
        )
    backlog = load_publication_backlog()
    owner_username, owner_machine = _current_owner()

    entries = [
        _catalog_entry(
            transcript,
            agent_links.get(_path_key(transcript.absolute_path)),
            sidecars,
            backlog,
            owner_username=owner_username,
            owner_machine=owner_machine,
            target_resolution_failed=target_resolution_failed,
        )
        for transcript in transcripts
    ]
    filtered = [
        entry
        for entry in entries
        if _matches(
            entry,
            query=query,
            provenance=provenance,
            machine=machine,
            project=project,
        )
    ]
    counts: dict[ChatProvenance, int] = {
        value: sum(entry.provenance == value for entry in filtered)
        for value in CHAT_PROVENANCE_VALUES
    }
    remote_machines = frozenset(
        entry.source_machine
        for entry in filtered
        if entry.provenance == "remote" and entry.source_machine
    )
    truncated = limit is not None and len(filtered) > limit
    selected = filtered if limit is None else filtered[:limit]
    return ChatCatalogSnapshot(
        entries=tuple(selected),
        provenance_counts=counts,
        remote_machines=remote_machines,
        truncated=truncated,
        diagnostics=diagnostics,
    )


def _catalog_entry(
    transcript: ChatTranscriptInfo,
    link: AgentChatLink | None,
    sidecars: dict[str, SidecarProjectIndex],
    backlog: dict[tuple[str, str], PublicationBacklogItem],
    *,
    owner_username: str | None,
    owner_machine: str | None,
    target_resolution_failed: bool,
) -> ChatCatalogEntry:
    fallback_remote = _is_unlinked_import(transcript)
    published_agent, published_index = _published_agent(link, sidecars, owner_machine)
    if link is not None and link.imported:
        provenance: ChatProvenance = "remote"
    elif fallback_remote:
        provenance = "remote"
    elif published_agent is not None:
        provenance = "shared"
    elif link is None:
        provenance = "local"
    elif _sidecar_was_read(link.project_key, sidecars):
        provenance = "local"
    elif link.project_key not in sidecars and not target_resolution_failed:
        provenance = "local"
    else:
        provenance = "unknown"

    if provenance == "remote":
        source_machine = link.source_machine if link is not None else None
        source_username = link.source_username if link is not None else None
    else:
        source_machine = owner_machine
        source_username = owner_username

    owning_index = sidecars.get(link.project_key) if link is not None else None
    sidecar_repo = published_index.sidecar_path if published_index is not None else None
    if (
        sidecar_repo is None
        and provenance == "remote"
        and owning_index is not None
        and owning_index.readable
    ):
        sidecar_repo = owning_index.sidecar_path
    sidecar_relpath = published_agent.relpath if published_agent is not None else None
    publication = _publication_status(link, backlog)
    return ChatCatalogEntry(
        path=transcript.path,
        absolute_path=transcript.absolute_path,
        basename=transcript.basename,
        mtime=transcript.mtime,
        size_bytes=transcript.size_bytes,
        workflow=transcript.workflow,
        agent=transcript.agent,
        timestamp=transcript.timestamp,
        prompt_snippet=transcript.prompt_snippet,
        response_snippet=transcript.response_snippet,
        provenance=provenance,
        source_machine=source_machine,
        source_username=source_username,
        project_key=link.project_key if link is not None else None,
        agent_artifact_dir=link.artifact_dir if link is not None else None,
        agent_local_name=link.local_name if link is not None else None,
        agent_global_name=link.global_name if link is not None else None,
        sidecar_repo=sidecar_repo,
        sidecar_relpath=sidecar_relpath,
        publication_pending=(publication is not None and not publication.quarantined),
        publication_last_error=(
            publication.last_error if publication is not None else None
        ),
        publication_quarantined=(
            publication.quarantined if publication is not None else False
        ),
        publication_attempts=(
            publication.attempts if publication is not None else None
        ),
    )


def _published_agent(
    link: AgentChatLink | None,
    sidecars: dict[str, SidecarProjectIndex],
    owner_machine: str | None,
) -> tuple[SidecarAgent | None, SidecarProjectIndex | None]:
    if link is None or link.global_name is None:
        return None, None
    candidates = [link.global_name]
    if owner_machine and link.local_name:
        candidates.append(
            machine_qualify_v1_transport_agent_name(link.local_name, owner_machine)
        )
    preferred = sidecars.get(link.project_key)
    indexes: Iterable[SidecarProjectIndex] = (
        (
            preferred,
            *(index for key, index in sidecars.items() if key != link.project_key),
        )
        if preferred is not None
        else sidecars.values()
    )
    for index in indexes:
        if not index.readable:
            continue
        for name in candidates:
            published = index.agents.get(name)
            if published is not None:
                return published, index
    return None, None


def _sidecar_was_read(
    project_key: str,
    sidecars: dict[str, SidecarProjectIndex],
) -> bool:
    index = sidecars.get(project_key)
    return index is not None and index.readable


def _publication_status(
    link: AgentChatLink | None,
    backlog: dict[tuple[str, str], PublicationBacklogItem],
) -> PublicationBacklogItem | None:
    if link is None:
        return None
    for name in (link.global_name, link.local_name):
        if name is None:
            continue
        key = (link.project_key, name)
        if key in backlog:
            return backlog[key]
    return None


def _matches(
    entry: ChatCatalogEntry,
    *,
    query: str | None,
    provenance: ChatProvenance | None,
    machine: str | None,
    project: str | None,
) -> bool:
    if provenance is not None and entry.provenance != provenance:
        return False
    if machine is not None and not _same(machine, entry.source_machine):
        return False
    if project is not None and not _same(project, entry.project_key):
        return False
    if not query:
        return True
    needle = query.casefold()
    values = (
        entry.path,
        entry.basename,
        entry.workflow,
        entry.agent,
        entry.agent_local_name,
        entry.agent_global_name,
        entry.prompt_snippet,
        entry.response_snippet,
    )
    return any(needle in value.casefold() for value in values if value)


def _same(expected: str, actual: str | None) -> bool:
    return actual is not None and expected.casefold() == actual.casefold()


def _is_unlinked_import(transcript: ChatTranscriptInfo) -> bool:
    path = Path(transcript.absolute_path)
    return (
        transcript.basename.startswith("imported-v2-")
        and not path.parent.name.isdigit()
    )


def _path_key(path: str) -> str:
    return str(Path(path).expanduser().resolve(strict=False))


def _current_owner() -> tuple[str | None, str | None]:
    try:
        owner = get_agent_owner_identity()
    except (ImportError, OSError, RuntimeError, ValueError):
        owner = None
    if owner is None:
        return None, None
    return owner.username, owner.machine_name


__all__ = ["load_chat_catalog"]
