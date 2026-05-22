"""Configured sibling repository resolution for launched agents."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any

import yaml  # type: ignore[import-untyped]

SIBLING_REPOS_JSON_ENV = "SASE_SIBLING_REPOS_JSON"
SIBLING_REPO_ENV_PREFIX = "SASE_SIBLING_REPO_"
SIBLING_REPO_ENV_SUFFIXES = ("_DIR", "_PRIMARY_DIR")

_VALID_WORKSPACE_STRATEGIES = {"suffix", "none"}


@dataclass(frozen=True)
class _ResolvedSiblingRepo:
    """Concrete sibling repository paths exposed to an agent run."""

    name: str
    env_name: str
    primary_dir: str
    workspace_dir: str
    workspace_num: int
    workspace_strategy: str

    def to_json_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "env_name": self.env_name,
            "primary_dir": self.primary_dir,
            "workspace_dir": self.workspace_dir,
            "workspace_num": self.workspace_num,
            "workspace_strategy": self.workspace_strategy,
        }


@dataclass(frozen=True)
class SiblingRepoResolution:
    """Resolved sibling repos plus non-fatal configuration warnings."""

    repos: tuple[_ResolvedSiblingRepo, ...]
    warnings: tuple[str, ...] = ()

    def to_jsonable(self) -> list[dict[str, object]]:
        return [repo.to_json_dict() for repo in self.repos]

    def to_json_env_value(self) -> str:
        return json.dumps(self.to_jsonable(), sort_keys=True)

    def to_env(self) -> dict[str, str]:
        if not self.repos:
            return {}
        env = {SIBLING_REPOS_JSON_ENV: self.to_json_env_value()}
        for repo in self.repos:
            env[f"{SIBLING_REPO_ENV_PREFIX}{repo.env_name}_DIR"] = repo.workspace_dir
            env[f"{SIBLING_REPO_ENV_PREFIX}{repo.env_name}_PRIMARY_DIR"] = (
                repo.primary_dir
            )
        return env


def scrub_sibling_repo_env(env: MutableMapping[str, str]) -> None:
    """Remove inherited sibling-repo env so a child gets only fresh mappings."""

    for key in list(env):
        if key == SIBLING_REPOS_JSON_ENV:
            env.pop(key, None)
        elif key.startswith(SIBLING_REPO_ENV_PREFIX) and key.endswith(
            SIBLING_REPO_ENV_SUFFIXES
        ):
            env.pop(key, None)


def apply_sibling_repo_env(
    env: MutableMapping[str, str], resolution: SiblingRepoResolution
) -> None:
    """Replace sibling-repo env in *env* with *resolution*."""

    scrub_sibling_repo_env(env)
    env.update(resolution.to_env())


def sibling_repo_metadata_from_env(
    env: Mapping[str, str] | None = None,
) -> list[dict[str, object]]:
    """Return the canonical sibling-repo metadata from env, if present."""

    source = os.environ if env is None else env
    raw = source.get(SIBLING_REPOS_JSON_ENV)
    if not raw:
        return []
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, list):
        return []
    metadata: list[dict[str, object]] = []
    for item in loaded:
        if isinstance(item, Mapping):
            metadata.append({str(key): value for key, value in item.items()})
    return metadata


def append_sibling_repo_prompt_note(
    prompt: str, resolution: SiblingRepoResolution
) -> str:
    """Append a concise workspace-matched sibling-repo note to *prompt*."""

    note = _build_sibling_repo_prompt_note(resolution)
    if not note:
        return prompt
    return f"{prompt.rstrip()}\n\n{note}\n"


def _build_sibling_repo_prompt_note(resolution: SiblingRepoResolution) -> str:
    """Build the agent-facing note for resolved sibling repositories."""

    if not resolution.repos:
        return ""
    lines = [
        "Sibling repos for this project are available in workspace-matched directories:"
    ]
    for repo in resolution.repos:
        lines.append(f"- {repo.name}: {repo.workspace_dir}")
    lines.append(
        "When editing a sibling repo, use its workspace-matched directory, not the primary checkout."
    )
    return "\n".join(lines)


def resolve_sibling_repos_for_project(
    *,
    project_file: str,
    workspace_dir: str,
    workspace_num: int,
    config: Mapping[str, Any] | None = None,
    materialize: bool = True,
) -> SiblingRepoResolution:
    """Resolve configured sibling repos for a launched project workspace."""

    primary_workspace_dir = _primary_workspace_dir(project_file, workspace_dir)
    entries = _configured_entries(primary_workspace_dir, config)
    return _resolve_sibling_repos(
        entries,
        primary_workspace_dir=primary_workspace_dir,
        workspace_num=workspace_num,
        materialize=materialize,
    )


def _resolve_sibling_repos(
    entries: Sequence[Mapping[str, Any]],
    *,
    primary_workspace_dir: str,
    workspace_num: int,
    materialize: bool = True,
) -> SiblingRepoResolution:
    """Resolve raw ``sibling_repos`` config entries into concrete paths."""

    primary_root = _normalize_path(primary_workspace_dir)
    resolved: list[_ResolvedSiblingRepo] = []
    warnings: list[str] = []
    used_env_names: set[str] = set()

    for entry in _dedupe_entries(entries):
        name = entry.get("name")
        raw_path = entry.get("path")
        if not isinstance(name, str) or not name.strip():
            warnings.append("Skipping sibling repo with missing name")
            continue
        if not isinstance(raw_path, str) or not raw_path.strip():
            warnings.append(f"Skipping sibling repo {name!r} with missing path")
            continue

        workspace = entry.get("workspace", {})
        if not isinstance(workspace, Mapping):
            workspace = {}
        strategy_raw = workspace.get("strategy", "suffix")
        strategy = str(strategy_raw or "suffix")
        if strategy not in _VALID_WORKSPACE_STRATEGIES:
            warnings.append(
                f"Skipping sibling repo {name!r}: unsupported workspace.strategy {strategy!r}"
            )
            continue

        primary_dir = _resolve_config_path(raw_path, relative_to=primary_root)
        if not Path(primary_dir).is_dir():
            warnings.append(
                f"Skipping sibling repo {name!r}: primary path does not exist: {primary_dir}"
            )
            continue

        try:
            workspace_dir = _resolve_workspace_dir(
                primary_dir,
                workspace_num=workspace_num,
                strategy=strategy,
                materialize=materialize,
            )
        except RuntimeError as exc:
            warnings.append(f"Skipping sibling repo {name!r}: {exc}")
            continue

        env_name = _unique_env_name(_sanitize_env_name(name), used_env_names)
        used_env_names.add(env_name)
        resolved.append(
            _ResolvedSiblingRepo(
                name=name,
                env_name=env_name,
                primary_dir=primary_dir,
                workspace_dir=workspace_dir,
                workspace_num=workspace_num,
                workspace_strategy=strategy,
            )
        )

    return SiblingRepoResolution(tuple(resolved), tuple(warnings))


def _primary_workspace_dir(project_file: str, workspace_dir: str) -> str:
    from sase.workspace_provider.utils import parse_workspace_dir

    parsed = parse_workspace_dir(project_file)
    if parsed:
        return _normalize_path(parsed)
    fallback = workspace_dir or os.getcwd()
    return _normalize_path(fallback)


def _configured_entries(
    primary_workspace_dir: str,
    config: Mapping[str, Any] | None,
) -> list[Mapping[str, Any]]:
    if config is not None:
        return _entries_from_config(config)

    from sase.config.core import load_merged_config

    merged = load_merged_config()
    entries = _entries_from_config(merged)

    local_config = _read_project_local_config(primary_workspace_dir)
    if local_config:
        entries.extend(_entries_from_config(local_config))
    return entries


def _entries_from_config(config: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = config.get("sibling_repos", [])
    if not isinstance(raw, list):
        return []
    entries: list[Mapping[str, Any]] = []
    for item in raw:
        if isinstance(item, Mapping):
            entries.append({str(key): value for key, value in item.items()})
    return entries


def _read_project_local_config(primary_workspace_dir: str) -> dict[str, Any]:
    path = Path(primary_workspace_dir) / "sase.yml"
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, yaml.YAMLError):
        return {}
    if isinstance(loaded, dict):
        return loaded
    return {}


def _dedupe_entries(
    entries: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    seen: set[str] = set()
    deduped: list[Mapping[str, Any]] = []
    for entry in entries:
        key = json.dumps(_json_safe_entry(entry), sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def _json_safe_entry(entry: Mapping[str, Any]) -> dict[str, object]:
    name = entry.get("name")
    path = entry.get("path")
    workspace = entry.get("workspace")
    strategy: object = None
    if isinstance(workspace, Mapping):
        strategy = workspace.get("strategy")
    return {
        "name": name if isinstance(name, str) else "",
        "path": path if isinstance(path, str) else "",
        "workspace_strategy": strategy if isinstance(strategy, str) else "",
    }


def _resolve_config_path(path: str, *, relative_to: str) -> str:
    expanded = os.path.expandvars(os.path.expanduser(path))
    candidate = Path(expanded)
    if not candidate.is_absolute():
        candidate = Path(relative_to) / candidate
    return _normalize_path(str(candidate))


def _normalize_path(path: str) -> str:
    return str(Path(path).expanduser().resolve(strict=False))


def _resolve_workspace_dir(
    primary_dir: str,
    *,
    workspace_num: int,
    strategy: str,
    materialize: bool,
) -> str:
    if strategy == "none" or workspace_num <= 1:
        return primary_dir

    if not materialize:
        return _suffix_workspace_path(primary_dir, workspace_num)

    from sase.workspace_provider.utils import ensure_workspace_checkout

    return _normalize_path(ensure_workspace_checkout(primary_dir, workspace_num))


def _suffix_workspace_path(primary_dir: str, workspace_num: int) -> str:
    primary = Path(primary_dir)
    return _normalize_path(str(primary.with_name(f"{primary.name}_{workspace_num}")))


def _sanitize_env_name(name: str) -> str:
    env_name = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper()
    return env_name or "REPO"


def _unique_env_name(base: str, used: set[str]) -> str:
    if base not in used:
        return base
    index = 2
    while f"{base}_{index}" in used:
        index += 1
    return f"{base}_{index}"
