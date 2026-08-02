"""Capture launch-time provenance for xprompt definition references."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import importlib.resources
import json
import os
from pathlib import Path
from typing import Literal, TypedDict

from sase._repo_inventory_models import RepoRecord
from sase.config import CONFIG_DIR, get_use_chezmoi
from sase.content_layout import (
    chezmoi_source_path,
    discover_project_root,
    resolve_project_config_read_path,
    resolve_project_layout,
)
from sase.repo_inventory import collect_repo_inventory
from sase.xprompt.models import XPrompt
from sase.xprompt.used_xprompts import scan_xprompt_references

_SCHEMA_VERSION = 1
_YAML_SUFFIXES = {".yaml", ".yml"}


class _XPromptSourceRecord(TypedDict):
    """JSON wire record consumed by the Rust xprompt-link rewriter."""

    schema_version: int
    raw_ref: str
    name: str
    kind: str
    source_kind: Literal["markdown", "yaml"] | None
    source_path: str | None
    definition_line: int | None
    repo: str | None
    repo_root: str | None
    repo_relpath: str | None
    chezmoi: bool
    skipped_reason: str | None


@dataclass(frozen=True)
class _DefinitionRepo:
    """Best-effort repository ownership for one definition path."""

    repo: str | None
    repo_root: str | None
    repo_relpath: str | None
    chezmoi: bool


def _collect_xprompt_sources(
    raw_prompt: str,
    *,
    extra_xprompts: dict[str, XPrompt] | None = None,
    swarm_xprompts: Sequence[str] | None = None,
) -> list[_XPromptSourceRecord]:
    """Return definition-provenance rows for launch xprompt references."""
    records: list[_XPromptSourceRecord] = []
    seen_raw_refs: set[str] = set()
    scanned_references = scan_xprompt_references(
        raw_prompt,
        extra_xprompts=extra_xprompts,
        swarm_xprompts=swarm_xprompts,
    )
    for scanned in scanned_references:
        if scanned.raw_ref in seen_raw_refs:
            continue
        seen_raw_refs.add(scanned.raw_ref)

        source_id = scanned.item.source_path if scanned.item is not None else None
        source_path = definition_file_for_source(source_id)
        source_kind = _source_kind(source_id, source_path)
        definition_repo = (
            _resolve_definition_repo(source_path)
            if source_path is not None
            else _DefinitionRepo(None, None, None, False)
        )
        definition_line = (
            definition_line_for(source_path, scanned.name)
            if source_kind == "yaml" and source_path is not None
            else None
        )
        skipped_reason = _skipped_reason(
            known=scanned.item is not None,
            source_id=source_id,
            source_path=source_path,
            definition_repo=definition_repo,
        )
        records.append(
            {
                "schema_version": _SCHEMA_VERSION,
                "raw_ref": scanned.raw_ref,
                "name": scanned.name,
                "kind": scanned.kind or "unknown",
                "source_kind": source_kind,
                "source_path": (
                    str(source_path) if source_path is not None else source_id
                ),
                "definition_line": definition_line,
                "repo": definition_repo.repo,
                "repo_root": definition_repo.repo_root,
                "repo_relpath": definition_repo.repo_relpath,
                "chezmoi": definition_repo.chezmoi,
                "skipped_reason": skipped_reason,
            }
        )
    return records


def _resolve_definition_repo(path: Path | str) -> _DefinitionRepo:
    """Resolve the deepest known repository that owns *path*.

    A definition already inside a repository wins directly. Otherwise, a
    home-managed definition is remapped into the chezmoi source tree when
    configured, then matched against the same inventory.
    """
    source = Path(path).expanduser().resolve(strict=False)
    inventory = collect_repo_inventory()

    direct = _match_inventory_repo(source, inventory.records)
    if direct is not None:
        repo, root, relpath = direct
        return _DefinitionRepo(repo, str(root), relpath, False)

    if not get_use_chezmoi() or not _is_relative_to(source, Path.home()):
        return _DefinitionRepo(None, None, None, False)

    remapped = chezmoi_source_path(source).expanduser().resolve(strict=False)
    mapped = _match_inventory_repo(remapped, inventory.records)
    if mapped is None:
        return _DefinitionRepo(None, None, None, remapped != source)
    repo, root, relpath = mapped
    return _DefinitionRepo(repo, str(root), relpath, remapped != source)


def definition_line_for(path: Path | str, name: str) -> int | None:
    """Return a unique YAML definition-key line, or ``None`` when uncertain."""
    source = Path(path).expanduser()
    if source.suffix.lower() not in _YAML_SUFFIXES:
        return None
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None

    candidates = [name]
    if "/" in name:
        candidates.append(name.rsplit("/", 1)[1])
    for candidate in dict.fromkeys(candidates):
        matches = _definition_key_lines(text, candidate)
        if len(matches) == 1:
            return matches[0]
        if matches:
            return None
    return None


_resolve_definition_line = definition_line_for


def write_xprompt_sources(
    artifacts_dir: str | os.PathLike[str] | None,
    raw_prompt: str,
    *,
    extra_xprompts: dict[str, XPrompt] | None = None,
    swarm_xprompts: Sequence[str] | None = None,
) -> list[_XPromptSourceRecord]:
    """Write ``xprompt_sources.json`` and return its provenance records."""
    records = _collect_xprompt_sources(
        raw_prompt,
        extra_xprompts=extra_xprompts,
        swarm_xprompts=swarm_xprompts,
    )
    if artifacts_dir is None:
        return records
    artifacts_path = Path(artifacts_dir)
    if not artifacts_path.is_dir():
        return records
    with open(artifacts_path / "xprompt_sources.json", "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)
    return records


def definition_file_for_source(source_id: str | None) -> Path | None:
    if not source_id:
        return None
    resolved: Path | None
    if source_id == "config":
        resolved = CONFIG_DIR / "sase.yml"
    elif source_id == "default_config":
        resolved = _resource_path("sase", "default_config.yml")
    elif source_id == "local_config":
        root = discover_project_root()
        resolved = resolve_project_config_read_path(root) if root is not None else None
    elif source_id.startswith("config_overlay:"):
        resolved = CONFIG_DIR / source_id.removeprefix("config_overlay:")
    elif source_id.startswith("project_local_config:"):
        resolved = _project_config_source(
            source_id.removeprefix("project_local_config:")
        )
    elif source_id.startswith("plugin_config:"):
        resolved = _plugin_source(
            source_id.removeprefix("plugin_config:"),
            filename="default_config.yml",
            capability="sase_config",
        )
    elif source_id.startswith("plugin:"):
        remainder = source_id.removeprefix("plugin:")
        if "/" not in remainder:
            return None
        module, filename = remainder.split("/", 1)
        resolved = _plugin_source(
            module,
            filename=f"xprompts/{filename}",
            capability="sase_xprompts",
        )
    elif source_id.startswith("builtin:sase/"):
        resolved = _resource_path("sase", source_id.removeprefix("builtin:sase/"))
    else:
        resolved = Path(source_id).expanduser()
        if not resolved.is_absolute():
            resolved = Path.cwd() / resolved

    return resolved.expanduser().resolve(strict=False) if resolved is not None else None


_definition_file_for_source = definition_file_for_source


def _resource_path(package: str, relative: str) -> Path | None:
    try:
        return Path(str(importlib.resources.files(package).joinpath(relative)))
    except (AttributeError, ModuleNotFoundError, TypeError):
        return None


def _plugin_source(module_name: str, *, filename: str, capability: str) -> Path | None:
    from sase.main.plugin_discovery import discover_plugin_resources

    for module in discover_plugin_resources(capability):
        if module.__name__ != module_name:
            continue
        return _resource_path(module.__name__, filename)
    return None


def _project_config_source(project: str) -> Path | None:
    from sase.xprompt.loader import get_known_project_workspaces
    from sase.xprompt.project_identity import canonical_xprompt_project

    namespace = canonical_xprompt_project(project) or project
    workspace = get_known_project_workspaces().get(namespace)
    if workspace is None:
        return None
    path = resolve_project_config_read_path(
        workspace,
        label=f"project config for {namespace}",
    )
    return path or resolve_project_layout(workspace).config.write_path


def _source_kind(
    source_id: str | None, source_path: Path | None
) -> Literal["markdown", "yaml"] | None:
    suffix = source_path.suffix.lower() if source_path is not None else ""
    if suffix == ".md":
        return "markdown"
    if suffix in _YAML_SUFFIXES:
        return "yaml"
    if source_id is not None and source_id.startswith(("config", "local_config")):
        return "yaml"
    return None


def _match_inventory_repo(
    path: Path, records: Sequence[RepoRecord]
) -> tuple[str, Path, str] | None:
    candidates: list[tuple[int, str, str, str, Path, str]] = []
    for record in records:
        raw_roots = (
            record.path,
            *(clone.path for clone in record.clones),
        )
        for raw_root in raw_roots:
            if not raw_root:
                continue
            root = Path(raw_root).expanduser().resolve(strict=False)
            try:
                relpath = path.relative_to(root).as_posix()
            except ValueError:
                continue
            candidates.append(
                (
                    len(root.parts),
                    record.name.casefold(),
                    str(root),
                    record.name,
                    root,
                    relpath,
                )
            )
    if not candidates:
        return None
    _depth, _folded_name, _root_text, name, root, relpath = sorted(
        candidates,
        key=lambda candidate: (-candidate[0], candidate[1], candidate[2]),
    )[0]
    return name, root, relpath


def _definition_key_lines(source_text: str, name: str) -> list[int]:
    matches: list[int] = []
    section_indent: int | None = None
    for line_number, line in enumerate(source_text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or line.startswith(("\t", "-")):
            continue
        indent = len(line) - len(line.lstrip(" "))
        key = _yaml_key_name(stripped)
        if key is None:
            continue
        if indent == 0:
            section_indent = 0 if key in {"workflows", "xprompts"} else None
            continue
        if section_indent is not None and indent > section_indent and key == name:
            matches.append(line_number)
    return matches


def _yaml_key_name(stripped_line: str) -> str | None:
    if ":" not in stripped_line:
        return None
    raw_key = stripped_line.split(":", 1)[0].strip()
    if not raw_key or raw_key.startswith("-"):
        return None
    if len(raw_key) >= 2 and raw_key[0] == raw_key[-1] and raw_key[0] in {"'", '"'}:
        return raw_key[1:-1]
    return raw_key


def _skipped_reason(
    *,
    known: bool,
    source_id: str | None,
    source_path: Path | None,
    definition_repo: _DefinitionRepo,
) -> str | None:
    if not known:
        return "unknown-reference"
    if source_id is None:
        return "missing-source-path"
    if source_path is None:
        return "unresolved-source-path"
    if definition_repo.repo is None:
        return "repository-not-found"
    return None


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.expanduser().resolve(strict=False))
    except ValueError:
        return False
    return True


__all__ = [
    "definition_file_for_source",
    "definition_line_for",
    "write_xprompt_sources",
]
