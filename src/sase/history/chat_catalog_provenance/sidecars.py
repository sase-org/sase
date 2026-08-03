"""Agents-sidecar and publication-outbox indexes for chat provenance."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3

from sase.agents_sync.git import run_git
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_outbox import (
    AGENT_PUBLICATION_OUTBOX_FILENAME,
    AgentPublicationOutboxItem,
    snapshot_agent_publications_from_path,
)
from sase.agents_sync.targets import resolve_sync_targets
from sase.agents_sync.v2_io import validate_component
from sase.core.paths import sase_projects_dir

from .cache import load_cached_json, store_cached_json
from .models import (
    PublicationBacklogItem,
    PublicationDisposition,
    SidecarAgent,
    SidecarProjectIndex,
)

_CACHE_NAMESPACE = "sidecar-committed-tree-v2"


def load_sidecar_indexes(
    cache: sqlite3.Connection,
    *,
    force: bool,
) -> tuple[dict[str, SidecarProjectIndex], tuple[str, ...], bool]:
    """Resolve configured sidecars and return indexes plus diagnostics.

    The final boolean is true only when target discovery itself failed, which
    lets classification distinguish "no sidecar configured" from "could not
    determine whether one is configured".
    """

    try:
        selection = resolve_sync_targets()
    except Exception as exc:  # noqa: BLE001 - diagnostic degradation boundary
        diagnostic = f"Could not resolve agents sidecars: {exc}"
        return {}, (diagnostic,), True

    diagnostics: list[str] = []
    indexes: dict[str, SidecarProjectIndex] = {}
    for outcome in selection.outcomes:
        if outcome.error:
            diagnostics.append(
                f"{outcome.project or outcome.project_key}: {outcome.error}"
            )
            indexes[outcome.project_key] = SidecarProjectIndex(
                project_key=outcome.project_key,
                sidecar_path="",
                readable=False,
                agents={},
                diagnostic=outcome.error,
            )
    for target in selection.targets:
        index = _load_project_sidecar(cache, target, force=force)
        indexes[target.project_key] = index
        if index.diagnostic:
            diagnostics.append(index.diagnostic)
    return indexes, tuple(dict.fromkeys(diagnostics)), False


def load_publication_backlog() -> tuple[
    dict[tuple[str, str], PublicationBacklogItem],
    tuple[str, ...],
]:
    """Read and aggregate typed outbox snapshots without mutating locks."""

    groups: dict[
        tuple[str, str],
        list[AgentPublicationOutboxItem],
    ] = defaultdict(list)
    diagnostics: list[str] = []
    projects_root = sase_projects_dir()
    try:
        projects = sorted(projects_root.iterdir(), key=lambda path: path.name)
    except OSError:
        return {}, ()
    for project_dir in projects:
        path = project_dir / AGENT_PUBLICATION_OUTBOX_FILENAME
        if not path.is_file():
            continue
        try:
            items = snapshot_agent_publications_from_path(path, project_dir.name)
        except (OSError, RuntimeError, ValueError) as exc:
            diagnostics.append(
                f"{project_dir.name}: could not load publication backlog: {exc}"
            )
            continue
        for item in items:
            if item.kind != "agent_hood":
                continue
            for name in {item.global_agent, item.local_agent}:
                groups[(project_dir.name, name)].append(item)
    result = {
        key: _aggregate_publications(tuple(items))
        for key, items in sorted(groups.items())
    }
    return result, tuple(diagnostics)


def _aggregate_publications(
    items: tuple[AgentPublicationOutboxItem, ...],
) -> PublicationBacklogItem:
    retired = sum(item.terminal for item in items)
    quarantined = sum(item.quarantined and not item.terminal for item in items)
    active = len(items) - retired - quarantined
    disposition: PublicationDisposition
    if active == len(items):
        disposition = "queued"
    elif quarantined == len(items):
        disposition = "quarantined"
    elif retired == len(items):
        disposition = "retired"
    else:
        disposition = "mixed"
    most_recent = max(
        items,
        key=lambda item: (
            item.updated_at,
            item.created_at,
            item.primary_revision,
            item.id,
        ),
    )
    return PublicationBacklogItem(
        attempts=max(item.attempts for item in items),
        last_error=(
            most_recent.terminal_reason or most_recent.last_error
            if most_recent.terminal
            else most_recent.last_error
        ),
        disposition=disposition,
    )


def _load_project_sidecar(
    cache: sqlite3.Connection,
    target: ProjectTarget,
    *,
    force: bool,
) -> SidecarProjectIndex:
    path = target.sidecar_path.expanduser()
    agents_dir = path / "agents"
    if not path.is_dir():
        diagnostic = (
            f"{target.project}: agents sidecar checkout is missing or unreadable "
            f"at {path}"
        )
        return SidecarProjectIndex(
            project_key=target.project_key,
            sidecar_path=str(path),
            readable=False,
            agents={},
            diagnostic=diagnostic,
        )
    is_git = (path / ".git").exists()
    head: str | None = None
    token: str | None
    if is_git:
        head = _git_head(path)
        if head is None:
            diagnostic = (
                f"{target.project}: could not read agents sidecar HEAD at {path}"
            )
            return SidecarProjectIndex(
                project_key=target.project_key,
                sidecar_path=str(path),
                readable=False,
                agents={},
                diagnostic=diagnostic,
            )
        token = f"git:{head}"
    else:
        token = _directory_token(agents_dir)
    if token is None:
        diagnostic = f"{target.project}: could not read agents sidecar HEAD at {path}"
        return SidecarProjectIndex(
            project_key=target.project_key,
            sidecar_path=str(path),
            readable=False,
            agents={},
            diagnostic=diagnostic,
        )

    if not force:
        payload = load_cached_json(
            cache,
            _CACHE_NAMESPACE,
            target.project_key,
            token,
        )
        decoded = _decode_agents(payload)
        if decoded is not None:
            return SidecarProjectIndex(
                project_key=target.project_key,
                sidecar_path=str(path),
                readable=True,
                agents=decoded,
            )

    if is_git:
        assert head is not None
        agents, tree_error = _scan_committed_agents(path, head)
    else:
        agents = _scan_agents_dir(agents_dir)
        tree_error = None
    if agents is None:
        diagnostic = (
            f"{target.project}: could not read committed agents sidecar tree at {path}"
            if tree_error is None
            else (
                f"{target.project}: could not read committed agents sidecar tree "
                f"at {path}: {tree_error}"
            )
        )
        return SidecarProjectIndex(
            project_key=target.project_key,
            sidecar_path=str(path),
            readable=False,
            agents={},
            diagnostic=diagnostic,
        )
    store_cached_json(
        cache,
        _CACHE_NAMESPACE,
        target.project_key,
        token,
        {name: asdict(agent) for name, agent in agents.items()},
    )
    return SidecarProjectIndex(
        project_key=target.project_key,
        sidecar_path=str(path),
        readable=True,
        agents=agents,
    )


def _git_head(path: Path) -> str | None:
    result = run_git(
        path,
        ["rev-parse", "HEAD"],
        op="chat_catalog.sidecar_head",
    )
    head = result.stdout.strip()
    return head if result.returncode == 0 and head else None


def _directory_token(agents_dir: Path) -> str | None:
    try:
        stat = agents_dir.stat()
    except OSError:
        return None
    return f"tree:{stat.st_mtime_ns}:{stat.st_size}"


def _scan_committed_agents(
    path: Path,
    head: str,
) -> tuple[dict[str, SidecarAgent] | None, str | None]:
    result = run_git(
        path,
        [
            "ls-tree",
            "-r",
            "--name-only",
            "-z",
            head,
            "--",
            "agents",
        ],
        op="chat_catalog.sidecar_tree",
    )
    if result.returncode != 0:
        return None, result.stderr.strip() or "git ls-tree failed"
    agents: dict[str, SidecarAgent] = {}
    for raw_path in result.stdout.split("\x00"):
        if not raw_path:
            continue
        parts = raw_path.split("/")
        if len(parts) != 3 or parts[0] != "agents" or parts[2] != "chat.md":
            continue
        try:
            name = validate_component(parts[1], label="published agent name")
        except ValueError:
            continue
        username, machine = _owner_from_global_name(name)
        agents[name] = SidecarAgent(
            global_name=name,
            machine=machine,
            username=username,
            relpath=raw_path,
        )
    return dict(sorted(agents.items())), None


def _scan_agents_dir(agents_dir: Path) -> dict[str, SidecarAgent] | None:
    try:
        directories = sorted(agents_dir.iterdir(), key=lambda entry: entry.name)
    except OSError:
        return None
    result: dict[str, SidecarAgent] = {}
    for directory in directories:
        try:
            chat_path = directory / "chat.md"
            if not directory.is_dir() or not chat_path.is_file():
                continue
        except OSError:
            continue
        metadata = _read_metadata(directory / "meta.json")
        machine = _metadata_text(metadata, "machine", "machine_name")
        username = _metadata_text(metadata, "username")
        parsed_username, parsed_machine = _owner_from_global_name(directory.name)
        result[directory.name] = SidecarAgent(
            global_name=directory.name,
            machine=machine or parsed_machine,
            username=username or parsed_username,
            relpath=f"agents/{directory.name}/chat.md",
        )
    return result


def _read_metadata(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _metadata_text(metadata: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _owner_from_global_name(name: str) -> tuple[str | None, str | None]:
    parts = name.split(".")
    if len(parts) >= 3:
        return parts[0], parts[1]
    if len(parts) >= 2:
        return None, parts[0]
    return None, None


def _decode_agents(payload: object) -> dict[str, SidecarAgent] | None:
    if not isinstance(payload, dict):
        return None
    result: dict[str, SidecarAgent] = {}
    try:
        for name, raw_agent in payload.items():
            if not isinstance(name, str) or not isinstance(raw_agent, dict):
                return None
            result[name] = SidecarAgent(**raw_agent)
    except (TypeError, ValueError):
        return None
    return result


__all__ = ["load_publication_backlog", "load_sidecar_indexes"]
