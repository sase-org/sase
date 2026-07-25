"""Agents-sidecar and publication-outbox indexes for chat provenance."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import sqlite3

from sase.agents_sync.git import run_git
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.targets import resolve_sync_targets
from sase.core.paths import sase_projects_dir

from .cache import load_cached_json, store_cached_json
from .models import SidecarAgent, SidecarProjectIndex

_CACHE_NAMESPACE = "sidecar"


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


def load_publication_backlog() -> dict[tuple[str, str], tuple[int | None, str | None]]:
    """Read pending global/local agent names without mutating outbox locks."""

    result: dict[tuple[str, str], tuple[int | None, str | None]] = {}
    projects_root = sase_projects_dir()
    try:
        projects = projects_root.iterdir()
    except OSError:
        return result
    for project_dir in projects:
        path = project_dir / "agents-publication-outbox.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            continue
        for item in payload["items"]:
            if not isinstance(item, dict):
                continue
            error = item.get("last_error")
            last_error = str(error) if isinstance(error, str) else None
            attempts_value = item.get("attempts")
            attempts = (
                attempts_value
                if isinstance(attempts_value, int)
                and not isinstance(attempts_value, bool)
                else None
            )
            for field in ("global_agent", "local_agent"):
                name = item.get(field)
                if isinstance(name, str) and name:
                    result[(project_dir.name, name)] = (attempts, last_error)
    return result


def _load_project_sidecar(
    cache: sqlite3.Connection,
    target: ProjectTarget,
    *,
    force: bool,
) -> SidecarProjectIndex:
    path = target.sidecar_path.expanduser()
    agents_dir = path / "agents"
    if not path.is_dir() or not agents_dir.is_dir():
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
    token = _sidecar_token(path, agents_dir)
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

    agents = _scan_agents_dir(agents_dir)
    if agents is None:
        diagnostic = f"{target.project}: agents sidecar is unreadable at {path}"
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


def _sidecar_token(path: Path, agents_dir: Path) -> str | None:
    if (path / ".git").exists():
        result = run_git(
            path,
            ["rev-parse", "HEAD"],
            op="chat_catalog.sidecar_head",
        )
        head = result.stdout.strip()
        if result.returncode != 0 or not head:
            return None
        return f"git:{head}"
    try:
        stat = agents_dir.stat()
    except OSError:
        return None
    return f"tree:{stat.st_mtime_ns}:{stat.st_size}"


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
