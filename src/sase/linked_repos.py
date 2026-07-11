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
import warnings

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
DEFAULT_LINKED_REPOS_CONFIG_KEY = "default_linked_repos"

DEFAULT_PLANS_DESCRIPTION = "Durable SASE plans, prompt snapshots, and bead state."
DEFAULT_RESEARCH_DESCRIPTION = "Durable SASE research reports and generated media."

_DEFAULT_LINKED_REPO_MARKER = "_sase_default_linked_repo"

# Host-scoped linked clones live inside the host checkout. Keep the legacy
# location during the compatibility window so existing clones (including WIP)
# can be discovered and migrated without recloning.
LINKED_REPO_CLONES_SUBDIR = ("sase", "repos")
LEGACY_LINKED_REPO_CLONES_SUBDIR = (".sase", "workspaces")

_OPENED_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class _ResolvedLinkedRepo:
    """Concrete linked repository paths exposed to an agent run."""

    name: str
    env_name: str
    primary_dir: str
    workspace_dir: str
    workspace_num: int
    auto_clone: bool = False

    @property
    def is_materialized(self) -> bool:
        """Return whether the workspace path can safely be exported."""

        return Path(self.workspace_dir).is_dir()

    def to_json_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "env_name": self.env_name,
            "primary_dir": self.primary_dir,
            "workspace_dir": self.workspace_dir,
            "workspace_num": self.workspace_num,
            "auto_clone": self.auto_clone,
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
            if not repo.is_materialized:
                continue
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


def is_legacy_static_linked_repo_record(mapping: Mapping[str, object]) -> bool:
    """Return whether *mapping* is an old shared-primary linked-repo record."""

    return mapping.get("workspace_strategy") == "none"


def record_opened_linked_repo(
    name: str,
    workspace_dir: str,
    *,
    reason: str = "",
    opened_at: str | None = None,
) -> None:
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
    normalized_reason = reason.strip()
    normalized_opened_at = (opened_at or "").strip()

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
            "reason": normalized_reason,
            "opened_at": normalized_opened_at,
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


def opened_linked_repo_records(artifact_root: Path | None) -> dict[str, dict[str, str]]:
    """Return full opened linked-repo records keyed by linked repo name.

    Unions both marker files; the canonical file wins when a name is recorded
    in both. Old v1 markers that lack ``reason`` or ``opened_at`` read back with
    empty strings for those fields.
    """

    if artifact_root is None:
        return {}
    records: dict[str, dict[str, str]] = {}
    for filename in (OPENED_LINKED_FILENAME, OPENED_SIBLINGS_FILENAME):
        for name, record in _opened_records(artifact_root / filename).items():
            records.setdefault(name, record)
    return records


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
        reason = item.get("reason")
        if not isinstance(reason, str):
            reason = ""
        opened_at = item.get("opened_at")
        if not isinstance(opened_at, str):
            opened_at = ""
        normalized_name = name.strip()
        records[normalized_name] = {
            "name": normalized_name,
            "workspace_dir": workspace_dir,
            "reason": reason.strip(),
            "opened_at": opened_at.strip(),
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
    local_config = _read_project_local_config(primary_workspace_dir)
    resolution_config = _resolution_config(primary_workspace_dir, config)
    entries, merge_warnings = _merged_entries_from_config(resolution_config)
    entries = _inject_default_linked_repos(
        entries,
        primary_workspace_dir=primary_workspace_dir,
        local_config=config if config is not None else local_config,
    )
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
        auto_clone = entry.get("auto_clone") is True
        if not isinstance(name, str) or not name.strip():
            warnings.append("Skipping linked repo with missing name")
            continue
        if not isinstance(raw_path, str) or not raw_path.strip():
            warnings.append(f"Skipping linked repo {name!r} with missing path")
            continue

        if "workspace" in entry:
            warnings.append(
                f"Linked repo {name!r} uses deprecated workspace configuration; "
                "ignoring it because linked workspaces are now host-scoped"
            )

        primary_dir = _resolve_config_path(raw_path, relative_to=primary_root)
        if not Path(primary_dir).is_dir():
            if entry.get(_DEFAULT_LINKED_REPO_MARKER) is True:
                continue
            warnings.append(
                f"Skipping linked repo {name!r}: primary path does not exist: {primary_dir}"
            )
            continue

        try:
            workspace_dir = _resolve_workspace_dir(
                primary_dir,
                name=name,
                host_primary_dir=primary_root,
                workspace_num=workspace_num,
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
                auto_clone=auto_clone,
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


def _inject_default_linked_repos(
    entries: Sequence[Mapping[str, Any]],
    *,
    primary_workspace_dir: str,
    local_config: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    """Inject managed-project companion repos unless locally disabled.

    The entries are derived solely from project-local configuration. Missing
    companion checkouts are marked so resolution can skip them quietly until
    the companion repositories have been created and materialized.
    """

    merged = list(entries)
    if local_config.get("is_sase_managed") is not True:
        return merged
    if local_config.get(DEFAULT_LINKED_REPOS_CONFIG_KEY) is False:
        return merged

    project_name = Path(primary_workspace_dir).resolve(strict=False).name
    if not project_name:
        return merged

    configured_names = {
        name.strip()
        for entry in entries
        if isinstance((name := entry.get("name")), str) and name.strip()
    }
    defaults = (
        (
            f"{project_name}--plans",
            DEFAULT_PLANS_DESCRIPTION,
            True,
        ),
        (
            f"{project_name}--research",
            DEFAULT_RESEARCH_DESCRIPTION,
            False,
        ),
    )
    for name, description, auto_clone in defaults:
        if name in configured_names:
            continue
        merged.append(
            {
                "name": name,
                "path": f"../{name}",
                "description": description,
                "auto_clone": auto_clone,
                _DEFAULT_LINKED_REPO_MARKER: True,
            }
        )
    return merged


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
    return {
        "name": name if isinstance(name, str) else "",
        "path": path if isinstance(path, str) else "",
        "auto_clone": entry.get("auto_clone") is True,
    }


def _resolve_config_path(path: str, *, relative_to: str) -> str:
    expanded = os.path.expandvars(os.path.expanduser(path))
    candidate = Path(expanded)
    if not candidate.is_absolute():
        candidate = Path(relative_to) / candidate
    return _normalize_path(str(candidate))


def _normalize_path(path: str) -> str:
    return str(Path(path).expanduser().resolve(strict=False))


def linked_repo_clone_dir(host_checkout: str | Path, name: str) -> str:
    """Return the canonical host-scoped clone path for linked repo *name*."""

    return _normalize_path(
        str(Path(host_checkout).joinpath(*LINKED_REPO_CLONES_SUBDIR, name))
    )


def _legacy_linked_repo_clone_dir(host_checkout: str | Path, name: str) -> str:
    return _normalize_path(
        str(Path(host_checkout).joinpath(*LEGACY_LINKED_REPO_CLONES_SUBDIR, name))
    )


def resolve_linked_repo_clone_dir(host_checkout: str | Path, name: str) -> str:
    """Resolve a linked clone without materializing or migrating it.

    The canonical path wins whenever it exists. A legacy-only clone remains
    visible to read-only callers until the next materializing operation moves
    it into the canonical location.
    """

    canonical = linked_repo_clone_dir(host_checkout, name)
    legacy = _legacy_linked_repo_clone_dir(host_checkout, name)
    if not Path(canonical).exists() and Path(legacy).exists():
        return legacy
    return canonical


def _linked_repo_clone_location(
    workspace_dir: str | Path,
) -> tuple[Path, str] | None:
    """Return ``(host_checkout, name)`` for a known linked-clone layout."""

    path = Path(workspace_dir).expanduser().resolve(strict=False)
    if len(path.parents) < 3:
        return None
    parent_pair = (path.parent.parent.name, path.parent.name)
    if parent_pair not in {
        LINKED_REPO_CLONES_SUBDIR,
        LEGACY_LINKED_REPO_CLONES_SUBDIR,
    }:
        return None
    return path.parents[2], path.name


def _prepare_linked_repo_clone_dir(host_checkout: Path, name: str) -> str:
    """Protect and migrate a host-scoped linked clone before materialization."""

    from sase.workspace_provider.git_exclude import ensure_git_info_exclude_entry

    ensure_git_info_exclude_entry(str(host_checkout), "/sase/repos/")
    canonical = Path(linked_repo_clone_dir(host_checkout, name))
    legacy = Path(_legacy_linked_repo_clone_dir(host_checkout, name))

    if canonical.exists() and legacy.exists():
        warnings.warn(
            f"Both canonical and legacy linked-repo clones exist for {name!r}; "
            f"using {canonical} and leaving stale legacy clone {legacy}",
            RuntimeWarning,
            stacklevel=3,
        )
        return str(canonical)

    if legacy.exists() and not canonical.exists():
        canonical.parent.mkdir(parents=True, exist_ok=True)
        os.rename(legacy, canonical)
        try:
            legacy.parent.rmdir()
        except OSError:
            pass
    return str(canonical)


def _resolve_workspace_dir(
    primary_dir: str,
    *,
    name: str,
    host_primary_dir: str,
    workspace_num: int,
    config: Mapping[str, Any],
    materialize: bool,
) -> str:
    if workspace_num <= 1:
        return primary_dir

    from sase.workspace_provider.store import WorkspaceStore

    host_workspace_dir = (
        WorkspaceStore(host_primary_dir, config=config)
        .resolve(workspace_num)
        .checkout_dir.rstrip("/")
    )
    target = resolve_linked_repo_clone_dir(host_workspace_dir, name)
    if not materialize:
        return target

    return materialize_linked_repo_workspace(
        primary_dir=primary_dir,
        workspace_dir=target,
        workspace_num=workspace_num,
    )


def materialize_linked_repo_workspace(
    *, primary_dir: str, workspace_dir: str, workspace_num: int
) -> str:
    """Clone a host-scoped linked workspace and initialize its SDD companion."""

    from sase.workspace_provider.utils import ensure_git_clone_at

    location = _linked_repo_clone_location(workspace_dir)
    if location is not None:
        host_checkout, name = location
        workspace_dir = _prepare_linked_repo_clone_dir(host_checkout, name)

    checkout_dir = ensure_git_clone_at(primary_dir, workspace_num, workspace_dir)
    try:
        from sase.sdd.store import ensure_workspace_sdd_clone

        ensure_workspace_sdd_clone(checkout_dir, workspace_num)
    except Exception:
        pass
    return _normalize_path(checkout_dir)


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
