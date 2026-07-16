"""Configuration merging and defaults for linked repositories."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
from typing import Any
from urllib.parse import urlparse

import yaml  # type: ignore[import-untyped]

from sase._git_remote import canonical_ssh_remote, parse_hosted_git_remote
from sase.content_layout import resolve_project_config_read_path

REPOS_CONFIG_KEY = "repos"
REPOS_LINKED_CONFIG_KEY = "linked"
REPOS_SIDECAR_CONFIG_KEY = "sidecar"
LINKED_REPOS_CONFIG_KEY = "linked_repos"
SIBLING_REPOS_CONFIG_KEY = "sibling_repos"
DEFAULT_LINKED_REPOS_CONFIG_KEY = "default_linked_repos"

DEFAULT_PLANS_DESCRIPTION = "Durable SASE plans, prompt snapshots, and bead state."
DEFAULT_RESEARCH_DESCRIPTION = "Durable SASE research reports and generated media."

_DEFAULT_LINKED_REPO_MARKER = "_sase_default_linked_repo"
_SIDECAR_REPO_MARKER = "_sase_sidecar_repo"
_SIDECAR_ROLE_KEY = "_sase_sidecar_role"
_SIDECAR_SLUG_KEY = "_sase_sidecar_slug"
_SIDECAR_REMOTE_URL_KEY = "_sase_sidecar_remote_url"
_SIDECAR_REPO_REF_KEY = "_sase_sidecar_repo_ref"


@dataclass(frozen=True)
class _SidecarRepoIdentity:
    """Resolved role, repository slug, and remote for one sidecar entry."""

    role: str
    slug: str
    repo: str
    remote_url: str | None


@dataclass(frozen=True)
class _GitHubRepoIdentity:
    """GitHub host and repository identity selected by the primary origin."""

    host: str
    repo: str


def resolution_config(
    primary_workspace_dir: str,
    config: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    if config is not None:
        return config

    from sase.config.core import load_merged_config

    merged = load_merged_config()
    local_config = read_project_local_config(primary_workspace_dir)
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
    """Merge ``repos.linked`` with its deprecated top-level aliases.

    Within a single key, exact duplicates are deduped but distinct same-name
    entries remain. Across keys, the precedence chain is ``repos.linked``,
    ``linked_repos``, then ``sibling_repos``. Divergent lower-precedence
    entries with the same name produce a non-fatal warning.
    """

    sources = (
        (
            "repos.linked",
            _dedupe_entries(_entries_for_repos_key(config, REPOS_LINKED_CONFIG_KEY)),
        ),
        (
            LINKED_REPOS_CONFIG_KEY,
            _dedupe_entries(_entries_for_key(config, LINKED_REPOS_CONFIG_KEY)),
        ),
        (
            SIBLING_REPOS_CONFIG_KEY,
            _dedupe_entries(_entries_for_key(config, SIBLING_REPOS_CONFIG_KEY)),
        ),
    )
    merged: list[Mapping[str, Any]] = []
    selected_by_name: dict[str, tuple[str, Mapping[str, Any]]] = {}
    warnings: list[str] = []
    for source_name, entries in sources:
        for entry in entries:
            name = entry.get("name")
            key_name = name.strip() if isinstance(name, str) else ""
            selected = selected_by_name.get(key_name) if key_name else None
            if selected is not None:
                selected_source, selected_entry = selected
                if not _entries_equivalent(selected_entry, entry):
                    warnings.append(
                        f"Linked repo {key_name!r} is defined in both "
                        f"{selected_source} and {source_name} with different "
                        f"settings; using the {selected_source} definition and "
                        f"ignoring the {source_name} one"
                    )
                continue
            merged.append(entry)
            if key_name:
                selected_by_name[key_name] = (source_name, entry)

    return merged, warnings


def merged_sidecar_entries_from_config(
    config: Mapping[str, Any],
    *,
    primary_workspace_dir: str,
) -> list[Mapping[str, Any]]:
    """Return merged, normalized ``repos.sidecar`` entries.

    Config-list concatenation preserves layer order, so later entries are
    project-local overrides of earlier global entries. Entries are merged by
    role name or resolved repository slug. A disabled override deliberately
    remains in the result so it can suppress both earlier config and implicit
    or store-record fallbacks.
    """

    raw_entries = _entries_for_repos_key(config, REPOS_SIDECAR_CONFIG_KEY)
    merged: list[dict[str, Any]] = []
    tokens_by_index: list[set[str]] = []
    for raw_entry in raw_entries:
        entry = dict(raw_entry)
        tokens = _sidecar_entry_tokens(entry, primary_workspace_dir, config)
        matched_index = next(
            (
                index
                for index, existing_tokens in enumerate(tokens_by_index)
                if tokens and tokens.intersection(existing_tokens)
            ),
            None,
        )
        if matched_index is None:
            merged.append(entry)
            tokens_by_index.append(tokens)
            continue
        merged[matched_index].update(entry)
        tokens_by_index[matched_index] = _sidecar_entry_tokens(
            merged[matched_index], primary_workspace_dir, config
        )

    normalized: list[Mapping[str, Any]] = []
    primary = Path(primary_workspace_dir).expanduser().resolve(strict=False)
    for entry in merged:
        identity = _sidecar_repo_identity(
            entry,
            primary_workspace_dir=str(primary),
            config=config,
        )
        normalized_entry = dict(entry)
        normalized_entry.setdefault("auto_clone", False)
        normalized_entry.setdefault("visibility", "public")
        normalized_entry.setdefault("disabled", False)
        normalized_entry[_SIDECAR_REPO_MARKER] = True
        if identity is not None:
            normalized_entry["name"] = identity.role
            normalized_entry.setdefault(
                "path", str(primary / "sase" / "repos" / identity.role)
            )
            normalized_entry[_SIDECAR_ROLE_KEY] = identity.role
            normalized_entry[_SIDECAR_SLUG_KEY] = identity.slug
            normalized_entry[_SIDECAR_REPO_REF_KEY] = identity.repo
            normalized_entry[_SIDECAR_REMOTE_URL_KEY] = identity.remote_url
        normalized.append(normalized_entry)
    return normalized


def merged_repo_entries_from_config(
    config: Mapping[str, Any],
    *,
    primary_workspace_dir: str,
) -> tuple[list[Mapping[str, Any]], list[str]]:
    """Return canonical linked entries followed by configured sidecars."""

    linked, warnings = _merged_entries_from_config(config)
    sidecars = merged_sidecar_entries_from_config(
        config,
        primary_workspace_dir=primary_workspace_dir,
    )
    return [*linked, *sidecars], warnings


def _sidecar_repo_identity(
    entry: Mapping[str, Any],
    *,
    primary_workspace_dir: str,
    config: Mapping[str, Any] | None = None,
) -> _SidecarRepoIdentity | None:
    """Resolve one configured sidecar's role, slug, repo ref, and remote URL."""

    role_value = entry.get("name")
    role = role_value.strip() if isinstance(role_value, str) else ""
    if not role:
        return None

    primary = Path(primary_workspace_dir).expanduser().resolve(strict=False)
    store_repo, store_remote = _store_sidecar_identity(primary, role)
    configured_repo = entry.get("repo")
    repo = configured_repo.strip() if isinstance(configured_repo, str) else ""
    if not repo:
        derived_repo = _derived_sidecar_repo(primary, role, config=config)
        if entry.get(_DEFAULT_LINKED_REPO_MARKER) is True:
            repo = store_repo or derived_repo
        else:
            # An explicit config entry without a pin opts into the current
            # project's owner/name convention.  A compatibility store record
            # may describe an older shared sidecar and must not override that
            # project-local identity.
            repo = derived_repo

    slug = _repo_basename(repo)
    if not slug:
        return None

    stored_remote: str | None = None
    if (
        store_repo
        and _repo_refs_match(store_repo, repo)
        and store_remote is not None
        and _remote_url_identifies_repo(store_remote, store_repo)
    ):
        stored_remote = store_remote

    github = _github_repo_identity_from_origin(primary, config=config)
    full_name = full_github_repo_name(primary, repo, config=config)
    remote_url = (
        canonical_ssh_remote(github.host, full_name)
        if github is not None and full_name is not None
        else stored_remote
    )

    return _SidecarRepoIdentity(
        role=role,
        slug=slug,
        repo=repo,
        remote_url=remote_url,
    )


def inject_default_linked_repos(
    entries: Sequence[Mapping[str, Any]],
    *,
    primary_workspace_dir: str,
    local_config: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    """Inject managed-project sidecar repos unless locally disabled."""

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
    configured_sidecar_tokens = {
        token
        for entry in entries
        for token in (
            _optional_entry_text(entry, _SIDECAR_ROLE_KEY),
            _optional_entry_text(entry, _SIDECAR_SLUG_KEY),
        )
        if token
    }
    defaults = (("plans", f"{project_name}--plans", DEFAULT_PLANS_DESCRIPTION, True),)
    for role, name, description, auto_clone in defaults:
        if name in configured_names or {role, name}.intersection(
            configured_sidecar_tokens
        ):
            continue
        merged.append(
            {
                "name": name,
                "path": f"../{name}",
                "description": description,
                "auto_clone": auto_clone,
                _DEFAULT_LINKED_REPO_MARKER: True,
                _SIDECAR_REPO_MARKER: True,
                _SIDECAR_ROLE_KEY: role,
                _SIDECAR_SLUG_KEY: name,
                _SIDECAR_REPO_REF_KEY: name,
                _SIDECAR_REMOTE_URL_KEY: None,
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


def _entries_for_repos_key(
    config: Mapping[str, Any], key: str
) -> list[Mapping[str, Any]]:
    repos = config.get(REPOS_CONFIG_KEY)
    if not isinstance(repos, Mapping):
        return []
    return _entries_for_key(repos, key)


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


def read_project_local_config(primary_workspace_dir: str) -> dict[str, Any]:
    path = resolve_project_config_read_path(primary_workspace_dir)
    if path is None:
        return {}
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
        "description": (
            entry.get("description")
            if isinstance(entry.get("description"), str)
            else ""
        ),
        "auto_clone": entry.get("auto_clone") is True,
    }


def _sidecar_entry_tokens(
    entry: Mapping[str, Any],
    primary_workspace_dir: str,
    config: Mapping[str, Any],
) -> set[str]:
    identity = _sidecar_repo_identity(
        entry,
        primary_workspace_dir=primary_workspace_dir,
        config=config,
    )
    if identity is None:
        return set()
    return {identity.role, identity.slug}


def _store_sidecar_identity(primary: Path, role: str) -> tuple[str, str | None]:
    if role not in {"plans", "research"}:
        return "", None
    try:
        from sase.sdd.store import read_sdd_store_record

        record = read_sdd_store_record(primary)
    except (OSError, RuntimeError, ValueError):
        return "", None
    if record is None:
        return "", None
    sidecar = record.sidecar_for_kind(role)
    if sidecar is None:
        return "", None
    return sidecar.repo, sidecar.remote_url


def _derived_sidecar_repo(
    primary: Path,
    role: str,
    *,
    config: Mapping[str, Any] | None = None,
) -> str:
    github = _github_repo_identity_from_origin(primary, config=config)
    project = github.repo if github is not None else None
    project_slug = project.rsplit("/", 1)[-1] if project else primary.name
    slug = f"{project_slug}--{role}"
    if project and "/" in project:
        owner = project.split("/", 1)[0]
        return f"{owner}/{slug}"
    return slug


def full_github_repo_name(
    primary: Path,
    repo: str,
    *,
    config: Mapping[str, Any] | None = None,
) -> str | None:
    cleaned = repo.strip().strip("/")
    if not cleaned:
        return None
    if "/" in cleaned:
        owner, slug = cleaned.split("/", 1)
        return f"{owner}/{slug}" if owner and slug and "/" not in slug else None
    github = _github_repo_identity_from_origin(primary, config=config)
    if github is None or "/" not in github.repo:
        return None
    return f"{github.repo.split('/', 1)[0]}/{cleaned}"


def _github_repo_identity_from_origin(
    primary: Path,
    *,
    config: Mapping[str, Any] | None,
) -> _GitHubRepoIdentity | None:
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=primary,
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    remote = result.stdout.strip()
    if not remote:
        return None

    parsed = parse_hosted_git_remote(remote)
    if parsed is None or parsed.host not in _configured_github_hosts(config):
        return None
    parts = parsed.repo.split("/")
    if len(parts) != 2 or not all(parts):
        return None
    return _GitHubRepoIdentity(parsed.host, f"{parts[0]}/{parts[1]}")


def _configured_github_hosts(config: Mapping[str, Any] | None) -> frozenset[str]:
    hosts = {"github.com"}
    raw_hosts = config.get("github_hosts") if config is not None else None
    values = (
        raw_hosts
        if isinstance(raw_hosts, Sequence) and not isinstance(raw_hosts, str)
        else (raw_hosts,)
    )
    for value in values:
        if value is None:
            continue
        raw = str(value).strip().casefold().rstrip("/")
        if not raw:
            continue
        if "://" in raw:
            parsed_url = urlparse(raw)
            host = parsed_url.netloc.rsplit("@", 1)[-1]
        elif "@" in raw and "/" in raw.partition(":")[2]:
            parsed_remote = parse_hosted_git_remote(raw)
            host = parsed_remote.host if parsed_remote is not None else ""
        else:
            host = raw.split("/", 1)[0].rsplit("@", 1)[-1]
        if host:
            hosts.add(host)
    return frozenset(hosts)


def _repo_basename(repo: str) -> str:
    return repo.rstrip("/").rsplit("/", 1)[-1]


def _remote_url_identifies_repo(remote_url: str, repo: str) -> bool:
    """Return whether *remote_url* names the repository in *repo*."""

    expected = repo.strip().strip("/")
    if expected.endswith(".git"):
        expected = expected[: -len(".git")]
    if not expected:
        return False

    remote = remote_url.strip().rstrip("/")
    parsed = parse_hosted_git_remote(remote)
    if parsed is not None:
        remote_repo = parsed.repo
        compare_basename = "/" not in expected
    else:
        remote_repo = Path(remote).name
        compare_basename = True

    normalized_remote = remote_repo.strip().strip("/")
    if normalized_remote.endswith(".git"):
        normalized_remote = normalized_remote[: -len(".git")]
    if compare_basename:
        normalized_remote = normalized_remote.rsplit("/", 1)[-1]
        expected = expected.rsplit("/", 1)[-1]
    return normalized_remote.casefold() == expected.casefold()


def _repo_refs_match(left: str, right: str) -> bool:
    def normalize(value: str) -> str:
        normalized = value.strip().strip("/")
        if normalized.endswith(".git"):
            normalized = normalized[: -len(".git")]
        return normalized.casefold()

    normalized_left = normalize(left)
    normalized_right = normalize(right)
    if "/" in normalized_left and "/" in normalized_right:
        return normalized_left == normalized_right
    return _repo_basename(normalized_left) == _repo_basename(normalized_right)


def _optional_entry_text(entry: Mapping[str, Any], key: str) -> str:
    value = entry.get(key)
    return value.strip() if isinstance(value, str) else ""


def resolve_config_path(path: str, *, relative_to: str) -> str:
    expanded = os.path.expandvars(os.path.expanduser(path))
    candidate = Path(expanded)
    if not candidate.is_absolute():
        candidate = Path(relative_to) / candidate
    return normalize_path(str(candidate))


def normalize_path(path: str) -> str:
    return str(Path(path).expanduser().resolve(strict=False))
