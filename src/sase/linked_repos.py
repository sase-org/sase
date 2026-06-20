"""Configured linked repository resolution for launched agents.

This is the canonical implementation of the configured related-repository
feature. The public config key is ``linked_repos``; ``sibling_repos`` is a
deprecated alias that is still parsed during the compatibility window. The
legacy :mod:`sase.sibling_repos` module re-exports these primitives under their
old names.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any

import yaml  # type: ignore[import-untyped]

# Canonical linked-repo env vars and marker file.
LINKED_REPOS_JSON_ENV = "SASE_LINKED_REPOS_JSON"
LINKED_REPO_ENV_PREFIX = "SASE_LINKED_REPO_"
LINKED_REPO_ENV_SUFFIXES = ("_DIR", "_PRIMARY_DIR")
OPENED_LINKED_FILENAME = "opened_linked_workspaces.json"

# Deprecated sibling-repo aliases emitted alongside canonical values during the
# compatibility window so that mixed-version tooling and rollback remain safe.
SIBLING_REPOS_JSON_ENV = "SASE_SIBLING_REPOS_JSON"
SIBLING_REPO_ENV_PREFIX = "SASE_SIBLING_REPO_"
SIBLING_REPO_ENV_SUFFIXES = ("_DIR", "_PRIMARY_DIR")
OPENED_SIBLINGS_FILENAME = "opened_siblings.json"

# Canonical config key plus its deprecated alias.
LINKED_REPOS_CONFIG_KEY = "linked_repos"
SIBLING_REPOS_CONFIG_KEY = "sibling_repos"

_VALID_WORKSPACE_STRATEGIES = {"suffix", "none"}
_OPENED_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class _ResolvedLinkedRepo:
    """Concrete linked repository paths exposed to an agent run."""

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
class LinkedRepoResolution:
    """Resolved linked repos plus non-fatal configuration warnings."""

    repos: tuple[_ResolvedLinkedRepo, ...]
    warnings: tuple[str, ...] = ()

    def to_jsonable(self) -> list[dict[str, object]]:
        return [repo.to_json_dict() for repo in self.repos]

    def to_json_env_value(self) -> str:
        return json.dumps(self.to_jsonable(), sort_keys=True)

    def to_env(self) -> dict[str, str]:
        if not self.repos:
            return {}
        json_value = self.to_json_env_value()
        env = {
            LINKED_REPOS_JSON_ENV: json_value,
            SIBLING_REPOS_JSON_ENV: json_value,
        }
        for repo in self.repos:
            env[f"{LINKED_REPO_ENV_PREFIX}{repo.env_name}_DIR"] = repo.workspace_dir
            env[f"{LINKED_REPO_ENV_PREFIX}{repo.env_name}_PRIMARY_DIR"] = (
                repo.primary_dir
            )
            env[f"{SIBLING_REPO_ENV_PREFIX}{repo.env_name}_DIR"] = repo.workspace_dir
            env[f"{SIBLING_REPO_ENV_PREFIX}{repo.env_name}_PRIMARY_DIR"] = (
                repo.primary_dir
            )
        return env


def scrub_linked_repo_env(env: MutableMapping[str, str]) -> None:
    """Remove inherited linked- and sibling-repo env from *env*.

    Both prefixes are scrubbed so a child agent gets only fresh mappings and no
    stale inherited related-repo paths can leak in.
    """

    for key in list(env):
        if key in (LINKED_REPOS_JSON_ENV, SIBLING_REPOS_JSON_ENV):
            env.pop(key, None)
        elif key.startswith(LINKED_REPO_ENV_PREFIX) and key.endswith(
            LINKED_REPO_ENV_SUFFIXES
        ):
            env.pop(key, None)
        elif key.startswith(SIBLING_REPO_ENV_PREFIX) and key.endswith(
            SIBLING_REPO_ENV_SUFFIXES
        ):
            env.pop(key, None)


def apply_linked_repo_env(
    env: MutableMapping[str, str], resolution: LinkedRepoResolution
) -> None:
    """Replace linked- and sibling-repo env in *env* with *resolution*."""

    scrub_linked_repo_env(env)
    env.update(resolution.to_env())


def linked_repo_metadata_from_env(
    env: Mapping[str, str] | None = None,
) -> list[dict[str, object]]:
    """Return the canonical linked-repo metadata from env, if present.

    Reads the canonical ``SASE_LINKED_REPOS_JSON`` and falls back to the legacy
    ``SASE_SIBLING_REPOS_JSON`` so old agents and old env still resolve.
    """

    source = os.environ if env is None else env
    raw = source.get(LINKED_REPOS_JSON_ENV) or source.get(SIBLING_REPOS_JSON_ENV)
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


def record_opened_linked_repo(name: str, workspace_dir: str) -> None:
    """Record that the current agent run opened a configured linked repo.

    During the migration both the canonical ``opened_linked_workspaces.json``
    and the legacy ``opened_siblings.json`` markers are written.
    """

    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return

    normalized_name = name.strip()
    if not normalized_name:
        return

    root = Path(artifacts_dir).expanduser().resolve(strict=False)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return

    for filename, records_key in (
        (OPENED_LINKED_FILENAME, "linked_repos"),
        (OPENED_SIBLINGS_FILENAME, "siblings"),
    ):
        marker = root / filename
        records = _opened_records(marker)
        records[normalized_name] = {
            "name": normalized_name,
            "workspace_dir": _normalize_path(workspace_dir),
        }
        _write_opened_marker(marker, records, records_key)


def opened_linked_repo_names(artifact_root: Path | None) -> set[str]:
    """Return linked repo names opened during the agent run.

    Unions names found in both the canonical and legacy marker files.
    """

    if artifact_root is None:
        return set()
    names: set[str] = set()
    names.update(_opened_records(artifact_root / OPENED_LINKED_FILENAME))
    names.update(_opened_records(artifact_root / OPENED_SIBLINGS_FILENAME))
    return names


def opened_linked_repo_workspace_dirs(artifact_root: Path | None) -> dict[str, str]:
    """Return opened linked repo names mapped to their recorded workspace dirs.

    Unions both marker files; the canonical file wins when a name is recorded in
    both with different workspace dirs.
    """

    if artifact_root is None:
        return {}
    workspace_dirs: dict[str, str] = {}
    for filename in (OPENED_LINKED_FILENAME, OPENED_SIBLINGS_FILENAME):
        for name, record in _opened_records(artifact_root / filename).items():
            workspace_dirs.setdefault(name, record.get("workspace_dir", ""))
    return workspace_dirs


def _write_opened_marker(
    marker: Path, records: dict[str, dict[str, str]], records_key: str
) -> None:
    payload = {
        "schema_version": _OPENED_SCHEMA_VERSION,
        records_key: [records[key] for key in sorted(records)],
    }
    try:
        tmp = marker.with_name(f".{marker.name}.{os.getpid()}.tmp")
        tmp.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, marker)
    except OSError:
        pass


def _opened_records(marker: Path) -> dict[str, dict[str, str]]:
    try:
        loaded = json.loads(marker.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    if not isinstance(loaded, Mapping):
        return {}
    entries = loaded.get("linked_repos")
    if not isinstance(entries, list):
        entries = loaded.get("siblings")
    if not isinstance(entries, list):
        return {}

    records: dict[str, dict[str, str]] = {}
    for item in entries:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        workspace_dir = item.get("workspace_dir")
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(workspace_dir, str):
            workspace_dir = ""
        normalized_name = name.strip()
        records[normalized_name] = {
            "name": normalized_name,
            "workspace_dir": workspace_dir,
        }
    return records


def resolve_linked_repos_for_project(
    *,
    project_file: str,
    workspace_dir: str,
    workspace_num: int,
    config: Mapping[str, Any] | None = None,
    materialize: bool = True,
) -> LinkedRepoResolution:
    """Resolve configured linked repos for a launched project workspace."""

    primary_workspace_dir = _primary_workspace_dir(project_file, workspace_dir)
    resolution_config = _resolution_config(primary_workspace_dir, config)
    entries, merge_warnings = _merged_entries_from_config(resolution_config)
    resolution = _resolve_linked_repos(
        entries,
        primary_workspace_dir=primary_workspace_dir,
        workspace_num=workspace_num,
        config=resolution_config,
        materialize=materialize,
    )
    if merge_warnings:
        return LinkedRepoResolution(
            resolution.repos,
            (*merge_warnings, *resolution.warnings),
        )
    return resolution


def _resolve_linked_repos(
    entries: Sequence[Mapping[str, Any]],
    *,
    primary_workspace_dir: str,
    workspace_num: int,
    config: Mapping[str, Any],
    materialize: bool = True,
) -> LinkedRepoResolution:
    """Resolve merged linked-repo config entries into concrete paths."""

    primary_root = _normalize_path(primary_workspace_dir)
    resolved: list[_ResolvedLinkedRepo] = []
    warnings: list[str] = []
    used_env_names: set[str] = set()

    for entry in entries:
        name = entry.get("name")
        raw_path = entry.get("path")
        if not isinstance(name, str) or not name.strip():
            warnings.append("Skipping linked repo with missing name")
            continue
        if not isinstance(raw_path, str) or not raw_path.strip():
            warnings.append(f"Skipping linked repo {name!r} with missing path")
            continue

        workspace = entry.get("workspace", {})
        if not isinstance(workspace, Mapping):
            workspace = {}
        strategy_raw = workspace.get("strategy", "suffix")
        strategy = str(strategy_raw or "suffix")
        if strategy not in _VALID_WORKSPACE_STRATEGIES:
            warnings.append(
                f"Skipping linked repo {name!r}: unsupported workspace.strategy {strategy!r}"
            )
            continue

        primary_dir = _resolve_config_path(raw_path, relative_to=primary_root)
        if not Path(primary_dir).is_dir():
            warnings.append(
                f"Skipping linked repo {name!r}: primary path does not exist: {primary_dir}"
            )
            continue

        try:
            workspace_dir = _resolve_workspace_dir(
                primary_dir,
                workspace_num=workspace_num,
                strategy=strategy,
                config=config,
                materialize=materialize,
            )
        except RuntimeError as exc:
            warnings.append(f"Skipping linked repo {name!r}: {exc}")
            continue

        env_name = _unique_env_name(_sanitize_env_name(name), used_env_names)
        used_env_names.add(env_name)
        resolved.append(
            _ResolvedLinkedRepo(
                name=name,
                env_name=env_name,
                primary_dir=primary_dir,
                workspace_dir=workspace_dir,
                workspace_num=workspace_num,
                workspace_strategy=strategy,
            )
        )

    return LinkedRepoResolution(tuple(resolved), tuple(warnings))


def _primary_workspace_dir(project_file: str, workspace_dir: str) -> str:
    from sase.workspace_provider.utils import parse_workspace_dir

    parsed = parse_workspace_dir(project_file)
    if parsed:
        return _normalize_path(parsed)
    fallback = workspace_dir or os.getcwd()
    return _normalize_path(fallback)


def _resolution_config(
    primary_workspace_dir: str,
    config: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    if config is not None:
        return config

    from sase.config.core import load_merged_config

    merged = load_merged_config()
    local_config = _read_project_local_config(primary_workspace_dir)
    if local_config:
        return _merge_resolution_config(merged, local_config)
    return merged


def _merge_resolution_config(
    base: Mapping[str, Any], override: Mapping[str, Any]
) -> dict[str, Any]:
    result: dict[str, Any] = dict(base)
    for key, override_value in override.items():
        base_value = result.get(key)
        if isinstance(base_value, Mapping) and isinstance(override_value, Mapping):
            result[key] = _merge_resolution_config(base_value, override_value)
        elif isinstance(base_value, list) and isinstance(override_value, list):
            result[key] = [*base_value, *override_value]
        else:
            result[key] = override_value
    return result


def _merged_entries_from_config(
    config: Mapping[str, Any],
) -> tuple[list[Mapping[str, Any]], list[str]]:
    """Merge canonical ``linked_repos`` with deprecated ``sibling_repos``.

    The merge/conflict rules below govern combining the two config *keys*. Within
    a single key the historical behavior is preserved: exact duplicates are
    deduped, but distinct same-name entries (for example a globally-configured
    repo extended by a project-local one) still flow through and receive
    ``_2`` env aliases.

    Cross-key rules:

    - legacy-only names continue to work;
    - canonical entries win for names also defined in the legacy key;
    - exact cross-key duplicates are deduped silently;
    - a legacy entry that diverges from a canonical entry of the same name is
      dropped with a non-fatal warning instead of silently creating a ``_2``
      env alias.
    """

    canonical = _dedupe_entries(_entries_for_key(config, LINKED_REPOS_CONFIG_KEY))
    legacy = _dedupe_entries(_entries_for_key(config, SIBLING_REPOS_CONFIG_KEY))

    canonical_by_name: dict[str, Mapping[str, Any]] = {}
    for entry in canonical:
        name = entry.get("name")
        if isinstance(name, str) and name.strip():
            canonical_by_name.setdefault(name.strip(), entry)

    merged: list[Mapping[str, Any]] = list(canonical)
    warnings: list[str] = []
    for entry in legacy:
        name = entry.get("name")
        key_name = name.strip() if isinstance(name, str) else ""
        canonical_entry = canonical_by_name.get(key_name) if key_name else None
        if canonical_entry is not None:
            if not _entries_equivalent(canonical_entry, entry):
                warnings.append(
                    f"Linked repo {key_name!r} is defined in both linked_repos "
                    "and sibling_repos with different settings; using the "
                    "linked_repos definition and ignoring the sibling_repos one"
                )
            continue  # canonical wins; drop the legacy duplicate
        merged.append(entry)

    return merged, warnings


def _entries_for_key(config: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    raw = config.get(key, [])
    if not isinstance(raw, list):
        return []
    entries: list[Mapping[str, Any]] = []
    for item in raw:
        if isinstance(item, Mapping):
            entries.append({str(name): value for name, value in item.items()})
    return entries


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


def _read_project_local_config(primary_workspace_dir: str) -> dict[str, Any]:
    path = Path(primary_workspace_dir) / "sase.yml"
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, yaml.YAMLError):
        return {}
    if isinstance(loaded, dict):
        return loaded
    return {}


def _entries_equivalent(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return _json_safe_entry(left) == _json_safe_entry(right)


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
    config: Mapping[str, Any],
    materialize: bool,
) -> str:
    if strategy == "none" or workspace_num <= 1:
        return primary_dir

    if not materialize:
        from sase.workspace_provider.store import WorkspaceStore

        return _normalize_path(
            WorkspaceStore(primary_dir, config=config)
            .resolve(workspace_num)
            .checkout_dir.rstrip("/")
        )

    from sase.workspace_provider.utils import ensure_workspace_checkout

    return _normalize_path(
        ensure_workspace_checkout(primary_dir, workspace_num, config=config)
    )


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
