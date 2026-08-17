"""Cheap in-process catalogs for live completion values.

Each fetcher imports its real dependencies inside the function so requesting
one kind never pays for the others. This module must stay off the
``sase.ace`` / ``sase.main.parser`` / ``rich`` / ``textual`` import set: the
candidates fast path forbids those packages. That means no
``sase.sdd`` / ``sase.bead`` / ``sase.workspace_provider`` / ``sase.xprompt``
/ ``sase.llm_provider`` package imports (their ``__init__`` modules pull the
forbidden set).
"""

from __future__ import annotations

import importlib.resources
import json
import os
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

from sase.completion.candidates.protocol import Candidate
from sase.completion.kinds import ValueKind

if TYPE_CHECKING:
    from sase.core.agent_scan_wire import AgentArtifactScanWire
    from sase.core.project_lifecycle_wire import ProjectRecordWire
    from sase.project_display_names import ProjectDisplaySnapshot

_Fetch = Callable[[str | None], list[Candidate]]
_SourcePath = Callable[[str | None], Path | None]
_PROMPT_SUFFIXES = frozenset({".md", ".yml", ".yaml"})
_SKIP_XPROMPT_DIR_NAMES = frozenset({"skills"})
_SKIP_PROMPT_NAMES = frozenset(
    {"skill.frame.template.md", "workflow.schema.json", "readme.md"}
)
_XPROMPT_TAGS: tuple[str, ...] = (
    "vcs",
    "crs",
    "fix_hook",
    "rollover",
    "mentor",
    "commit",
    "propose",
    "make_mentor_changes",
    "diff_file",
    "append_to_pr",
    "append_to_commit_and_propose",
    "create_epic_bead",
    "work_phase_bead",
    "work_task_bead",
    "land_epic",
)
_BUILTIN_MODEL_ALIASES: tuple[str, ...] = (
    "xsmall",
    "small",
    "medium",
    "large",
    "xlarge",
)


def _dedupe(candidates: Iterable[Candidate]) -> list[Candidate]:
    seen: set[str] = set()
    unique: list[Candidate] = []
    for candidate in candidates:
        if candidate.value in seen or not candidate.value:
            continue
        seen.add(candidate.value)
        unique.append(candidate)
    return unique


def _project_records_and_snapshot(
    project: str | None,
) -> tuple[list[ProjectRecordWire], ProjectDisplaySnapshot]:
    from sase.core.paths import sase_projects_dir
    from sase.core.project_lifecycle_facade import list_project_records
    from sase.core.project_lifecycle_wire import effective_project_name
    from sase.project_display_names import ProjectDisplaySnapshot

    records = list_project_records(sase_projects_dir(), "all", include_home=True)
    if project is not None:
        records = [
            record
            for record in records
            if record.project_name == project
            or effective_project_name(record) == project
        ]
    return records, ProjectDisplaySnapshot.from_records(records)


def _package_dir(*parts: str) -> Path | None:
    candidate = Path(str(importlib.resources.files("sase").joinpath(*parts)))
    return candidate if candidate.is_dir() else None


def _iter_named_files(
    root: Path, *, skip_dirs: frozenset[str] = frozenset()
) -> Iterator[Path]:
    if not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if name not in skip_dirs and not name.startswith(".")
        ]
        for filename in filenames:
            if filename.startswith("."):
                continue
            if filename.casefold() in _SKIP_PROMPT_NAMES:
                continue
            path = Path(dirpath) / filename
            if path.suffix.lower() in _PROMPT_SUFFIXES:
                yield path


def _read_json_object(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _resolve_beads_dir() -> Path | None:
    env = os.environ.get("SASE_SDD_BEADS_DIR")
    if env:
        path = Path(env)
        return path if path.is_dir() else None
    try:
        current = Path.cwd()
    except OSError:
        return None
    for parent in (current, *current.parents):
        for candidate in (
            parent / "sdd" / "beads",
            parent / ".sase" / "sdd" / "beads",
        ):
            if candidate.is_dir():
                return candidate
        if any((parent / marker).exists() for marker in (".git", ".hg", ".jj")):
            break
    return None


def _workspace_state_root() -> Path:
    override = os.environ.get("SASE_WORKSPACE_ROOT", "").strip()
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / "sase" / "workspaces"
    return Path.home() / ".local" / "state" / "sase" / "workspaces"


def _workspace_nums_from_registry(path: Path) -> list[tuple[int, str]]:
    payload = _read_json_object(path)
    if payload is None:
        return []
    raw = payload.get("workspaces")
    if not isinstance(raw, dict):
        return []
    found: list[tuple[int, str]] = []
    for key, value in raw.items():
        try:
            number = int(key)
        except (TypeError, ValueError):
            continue
        role = ""
        if isinstance(value, dict):
            role = str(value.get("role") or "")
        found.append((number, role))
    return found


def _repo_source_path(_project: str | None) -> Path | None:
    from sase.core.paths import sase_projects_dir

    return sase_projects_dir()


def _repo_candidates(project: str | None) -> list[Candidate]:
    records, snapshot = _project_records_and_snapshot(project)
    candidates: list[Candidate] = []
    for record in records:
        if not record.is_project:
            continue
        label = snapshot.label_for(record.project_name)
        names = [label]
        workspace_dir = (record.workspace_dir or "").strip()
        if workspace_dir:
            names.append(Path(workspace_dir).name)
        for name in names:
            candidates.append(Candidate(name, f"primary · {label}"))
    return _dedupe(candidates)


def _workspace_source_path(_project: str | None) -> Path | None:
    from sase.core.paths import sase_projects_dir

    return sase_projects_dir()


def _workspace_candidates(project: str | None) -> list[Candidate]:
    records, snapshot = _project_records_and_snapshot(project)
    state_root = _workspace_state_root()
    candidates: list[Candidate] = []
    for record in records:
        if not record.is_project:
            continue
        label = snapshot.label_for(record.project_name)
        candidates.append(Candidate("0", f"{label} primary"))
        seen = {0}
        registry_paths = [
            state_root / record.project_name / "registry.json",
        ]
        workspace_dir = (record.workspace_dir or "").strip()
        if workspace_dir:
            parent = Path(workspace_dir).expanduser()
            registry_paths.append(parent.parent / "registry.json")
            registry_paths.append(parent / ".sase" / "registry.json")
        for registry_path in registry_paths:
            for number, role in _workspace_nums_from_registry(registry_path):
                if number in seen:
                    continue
                seen.add(number)
                candidates.append(
                    Candidate(str(number), f"{label} {role or 'workspace'}")
                )
    return _dedupe(candidates)


def _flag_source_path(_project: str | None) -> Path | None:
    return None


def _flag_candidates(_project: str | None) -> list[Candidate]:
    from sase.feature_flags.registry import feature_flag_definitions

    return [
        Candidate(key, f"{definition.kind}: {definition.description}")
        for key, definition in feature_flag_definitions().items()
    ]


def _plugin_source_path(_project: str | None) -> Path | None:
    return None


def _plugin_candidates(_project: str | None) -> list[Candidate]:
    from sase.plugins.inventory import collect_plugin_inventory

    inventory = collect_plugin_inventory(load_resource_entry_points=False)
    values: list[Candidate] = []
    seen: set[str] = set()
    for dist in inventory.distributions:
        if dist.package.casefold() == "sase" or dist.package in seen:
            continue
        seen.add(dist.package)
        values.append(Candidate(dist.package, dist.version))
    for entry in inventory.third_party_entry_points:
        if entry.name in seen:
            continue
        seen.add(entry.name)
        values.append(Candidate(entry.name, entry.package))
    return values


def _plan_source_path(_project: str | None) -> Path | None:
    from sase.core.paths import sase_subdir

    return sase_subdir("plans")


def _plan_candidates(_project: str | None) -> list[Candidate]:
    from sase.core.paths import sase_subdir
    from sase.core.rust import require_rust_binding

    roots: list[Path] = [sase_subdir("plans")]
    try:
        cwd = Path.cwd()
    except OSError:
        cwd = None
    if cwd is not None:
        for parent in (cwd, *cwd.parents):
            for candidate in (
                parent / "sdd" / "plans",
                parent / ".sase" / "sdd" / "plans",
            ):
                if candidate.is_dir() and candidate not in roots:
                    roots.append(candidate)
            if any((parent / marker).exists() for marker in (".git", ".hg", ".jj")):
                break
    canonicalize = require_rust_binding("plan_reference_canonicalize")
    root_strings = [str(root) for root in roots]
    candidates: list[Candidate] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*/*.md")):
            try:
                reference = canonicalize(str(path), root_strings)
            except Exception:
                reference = None
            if not reference:
                reference = f"plan:{path.parent.name}/{path.name}"
            candidates.append(Candidate(str(reference), path.stem))
    return _dedupe(candidates)


def _patch_source_path(_project: str | None) -> Path | None:
    from sase.core.paths import sase_projects_dir

    return sase_projects_dir()


def _patch_candidates(project: str | None) -> list[Candidate]:
    from sase.core.rust import require_rust_binding

    records, snapshot = _project_records_and_snapshot(project)
    parse = require_rust_binding("parse_patch_project_bytes")
    candidates: list[Candidate] = []
    for record in records:
        project_label = snapshot.label_for(record.project_name)
        for raw_path in (record.project_file, record.archive_file):
            if not raw_path:
                continue
            path = Path(raw_path)
            try:
                payload = path.read_bytes()
            except OSError:
                continue
            try:
                parsed = parse(str(path), payload)
            except Exception:
                continue
            if not isinstance(parsed, list):
                continue
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "")
                if not name:
                    continue
                status = str(item.get("status") or "")
                display = str(item.get("project_display_name") or "") or project_label
                description = " · ".join(part for part in (status, display) if part)
                candidates.append(Candidate(name, description))
    return _dedupe(candidates)


def _memory_source_path(_project: str | None) -> Path | None:
    from sase.content_layout import discover_project_root, resolve_project_layout

    try:
        root = discover_project_root() or Path.cwd()
        return resolve_project_layout(root).memory.resolve_read("memory")
    except OSError:
        return None


def _memory_candidates(_project: str | None) -> list[Candidate]:
    memory_root = _memory_source_path(None)
    if memory_root is None or not memory_root.is_dir():
        return []
    candidates: list[Candidate] = []
    for path in sorted(memory_root.glob("*.md")):
        if path.name.casefold() == "readme.md":
            continue
        candidates.append(Candidate(path.name, "memory note"))
    return _dedupe(candidates)


def _xprompt_source_path(_project: str | None) -> Path | None:
    return None


def _xprompt_candidates(_project: str | None) -> list[Candidate]:
    from sase.content_layout import resolve_xprompt_file_sources

    roots: list[Path] = []
    packaged = _package_dir("xprompts")
    if packaged is not None:
        roots.append(packaged)
    defaults = _package_dir("default_xprompts")
    if defaults is not None:
        roots.append(defaults)
    try:
        roots.extend(
            source.path
            for source in resolve_xprompt_file_sources()
            if source.path is not None
        )
    except OSError:
        pass
    candidates: list[Candidate] = []
    for root in roots:
        for path in _iter_named_files(root, skip_dirs=_SKIP_XPROMPT_DIR_NAMES):
            relative = path.relative_to(root).with_suffix("")
            candidates.append(Candidate(relative.as_posix(), root.name))
    return _dedupe(candidates)


def _skill_source_path(_project: str | None) -> Path | None:
    return None


def _skill_candidates(_project: str | None) -> list[Candidate]:
    from sase.content_layout import resolve_skill_file_sources

    roots: list[Path] = []
    packaged = _package_dir("xprompts", "skills")
    if packaged is not None:
        roots.append(packaged)
    try:
        roots.extend(
            source.path
            for source in resolve_skill_file_sources()
            if source.path is not None
        )
    except OSError:
        pass
    candidates: list[Candidate] = []
    for root in roots:
        for path in _iter_named_files(root):
            candidates.append(Candidate(path.stem, "skill"))
    return _dedupe(candidates)


def _proc_source_path(_project: str | None) -> Path | None:
    from sase.core.paths import sase_subdir

    return sase_subdir("procs") / "procs.jsonl"


def _proc_candidates(project: str | None) -> list[Candidate]:
    from sase.core.rust import require_rust_binding

    path = _proc_source_path(project)
    if path is None or not path.is_file():
        return []
    try:
        payload = require_rust_binding("read_procs_snapshot")(str(path))
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []
    raw_procs = payload.get("procs")
    if raw_procs is None:
        raw_procs = payload.get("tasks")
    if not isinstance(raw_procs, list):
        return []
    candidates: list[Candidate] = []
    for item in raw_procs:
        if not isinstance(item, dict):
            continue
        if project is not None and str(item.get("project") or "") not in {project, ""}:
            continue
        proc_id = str(item.get("proc_id") or "")
        if not proc_id:
            continue
        status = str(item.get("status") or "")
        label = str(item.get("label") or "")
        candidates.append(
            Candidate(proc_id, " ".join(part for part in (status, label) if part))
        )
    return _dedupe(candidates)


def _monitor_source_path(_project: str | None) -> Path | None:
    from sase.core.agent_scan_facade import default_agent_artifact_index_path

    return default_agent_artifact_index_path()


def _query_agent_index(*, only_monitors: bool) -> AgentArtifactScanWire:
    from sase.core.agent_scan_facade import (
        default_agent_artifact_index_path,
        query_agent_artifact_index,
    )
    from sase.core.agent_scan_wire import AgentArtifactIndexQueryWire
    from sase.core.paths import sase_projects_dir

    return query_agent_artifact_index(
        default_agent_artifact_index_path(),
        sase_projects_dir(),
        query=AgentArtifactIndexQueryWire(
            only_monitors=only_monitors,
            freshness="cached",
        ),
    )


def _monitor_candidates(project: str | None) -> list[Candidate]:
    try:
        scan = _query_agent_index(only_monitors=True)
    except Exception:
        return []
    candidates: list[Candidate] = []
    for record in scan.records:
        if project is not None and record.project_name != project:
            continue
        meta = record.agent_meta
        if meta is None or meta.agent_family_role != "monitor" or not meta.monitor_id:
            continue
        description = meta.monitor_label or meta.name or ""
        candidates.append(Candidate(meta.monitor_id, description))
    return _dedupe(candidates)


def _artifact_source_path(_project: str | None) -> Path | None:
    from sase.core.paths import sase_home

    return sase_home() / "artifacts" / "index.jsonl"


def _artifact_candidates(project: str | None) -> list[Candidate]:
    from sase.core.rust import require_rust_binding

    index = _artifact_source_path(project)
    if index is None:
        return []
    filters: dict[str, object] = {
        "agent": None,
        "explicit_only": False,
        "kinds": None,
        "limit": 200,
        "project": project,
        "query": None,
        "since": None,
        "unused_only": False,
    }
    try:
        rows = require_rust_binding("artifact_files_query")(str(index), filters)
    except Exception:
        return []
    if not isinstance(rows, list):
        return []
    candidates: list[Candidate] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = str(row.get("id") or "")
        if not value:
            continue
        candidates.append(Candidate(value, str(row.get("label") or "")))
    return _dedupe(candidates)


def _tag_source_path(_project: str | None) -> Path | None:
    return None


def _tag_candidates(_project: str | None) -> list[Candidate]:
    return [Candidate(tag, "xprompt tag") for tag in _XPROMPT_TAGS]


def _agent_source_path(_project: str | None) -> Path | None:
    from sase.core.agent_scan_facade import default_agent_artifact_index_path

    return default_agent_artifact_index_path()


def _agent_candidates(project: str | None) -> list[Candidate]:
    try:
        scan = _query_agent_index(only_monitors=False)
    except Exception:
        return []
    _records, snapshot = _project_records_and_snapshot(project)
    candidates: list[Candidate] = []
    for record in scan.records:
        if project is not None and record.project_name != project:
            continue
        name = None
        if record.agent_meta is not None and record.agent_meta.name:
            name = record.agent_meta.name
        elif record.done is not None and record.done.name:
            name = record.done.name
        if not name:
            continue
        candidates.append(Candidate(name, snapshot.label_for(record.project_name)))
    return _dedupe(candidates)


def _model_source_path(_project: str | None) -> Path | None:
    return None


def _model_candidates(_project: str | None) -> list[Candidate]:
    return [Candidate(name, "builtin model alias") for name in _BUILTIN_MODEL_ALIASES]


def _bead_source_path(_project: str | None) -> Path | None:
    return _resolve_beads_dir()


def _bead_candidates(_project: str | None) -> list[Candidate]:
    beads_dir = _resolve_beads_dir()
    if beads_dir is None:
        return []
    from sase.core.rust import require_rust_binding

    try:
        payload = require_rust_binding("bead_list")(str(beads_dir), None, None, None)
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    candidates: list[Candidate] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        issue_id = str(item.get("id") or "")
        if not issue_id:
            continue
        candidates.append(Candidate(issue_id, str(item.get("title") or "")))
    return _dedupe(candidates)


PROVIDERS: dict[ValueKind, tuple[_Fetch, _SourcePath]] = {
    ValueKind.BEAD: (_bead_candidates, _bead_source_path),
    ValueKind.REPO: (_repo_candidates, _repo_source_path),
    ValueKind.WORKSPACE: (_workspace_candidates, _workspace_source_path),
    ValueKind.FLAG: (_flag_candidates, _flag_source_path),
    ValueKind.PLUGIN: (_plugin_candidates, _plugin_source_path),
    ValueKind.PLAN: (_plan_candidates, _plan_source_path),
    ValueKind.PATCH: (_patch_candidates, _patch_source_path),
    ValueKind.MEMORY: (_memory_candidates, _memory_source_path),
    ValueKind.XPROMPT: (_xprompt_candidates, _xprompt_source_path),
    ValueKind.SKILL: (_skill_candidates, _skill_source_path),
    ValueKind.PROC: (_proc_candidates, _proc_source_path),
    ValueKind.MONITOR: (_monitor_candidates, _monitor_source_path),
    ValueKind.ARTIFACT: (_artifact_candidates, _artifact_source_path),
    ValueKind.TAG: (_tag_candidates, _tag_source_path),
    ValueKind.AGENT: (_agent_candidates, _agent_source_path),
    ValueKind.MODEL: (_model_candidates, _model_source_path),
}


__all__ = ["PROVIDERS"]
