"""Repository identity and remote normalization for linked sidecars."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Any
from urllib.parse import urlparse

from sase._git_remote import canonical_ssh_remote, parse_hosted_git_remote


@dataclass(frozen=True)
class _GitHubRepoIdentity:
    """GitHub host and repository identity selected by the primary origin."""

    host: str
    repo: str


@dataclass(frozen=True)
class _SidecarRepoIdentity:
    """Resolved role, repository slug, and remote for one sidecar entry."""

    role: str
    slug: str
    repo: str
    remote_url: str | None


def resolve_sidecar_repo_identity(
    entry: Mapping[str, Any],
    *,
    primary_workspace_dir: str,
    default_entry: bool,
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
        if default_entry:
            repo = store_repo or derived_repo
        else:
            # An explicit config entry without a pin opts into the current
            # project's owner/name convention. A compatibility store record
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


def _store_sidecar_identity(primary: Path, role: str) -> tuple[str, str | None]:
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
    if parsed is None or parsed.host not in configured_github_hosts(config):
        return None
    parts = parsed.repo.split("/")
    if len(parts) != 2 or not all(parts):
        return None
    return _GitHubRepoIdentity(parsed.host, f"{parts[0]}/{parts[1]}")


def configured_github_hosts(config: Mapping[str, Any] | None) -> frozenset[str]:
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
