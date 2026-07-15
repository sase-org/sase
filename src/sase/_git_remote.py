"""Small transport-neutral helpers for hosted Git remote URLs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from urllib.parse import urlparse


@dataclass(frozen=True)
class _HostedGitRemote:
    """Host and repository path parsed from a hosted Git remote."""

    host: str
    repo: str


def parse_hosted_git_remote(value: str) -> _HostedGitRemote | None:
    """Parse scp-style and URL-style hosted Git remotes."""

    raw = value.strip()
    if not raw:
        return None

    host: str
    path: str
    if "://" not in raw:
        match = re.match(
            r"^(?:[^@/\s]+@)?(?P<host>[^:/\s]+):(?P<path>.+)$",
            raw,
        )
        if match is None:
            return None
        host = match.group("host")
        path = match.group("path")
    else:
        parsed = urlparse(raw)
        if parsed.hostname is None or not parsed.path:
            return None
        host = parsed.hostname
        try:
            port = parsed.port
        except ValueError:
            return None
        if port is not None:
            host = f"{host}:{port}"
        path = parsed.path

    normalized_host = host.strip().casefold().rstrip("/")
    normalized_repo = path.strip().strip("/")
    if normalized_repo.endswith(".git"):
        normalized_repo = normalized_repo[: -len(".git")]
    if not normalized_host or not normalized_repo:
        return None
    return _HostedGitRemote(normalized_host, normalized_repo)


def _git_remote_identity(value: str) -> str:
    """Return a transport-neutral identity for a hosted or local remote."""

    hosted = parse_hosted_git_remote(value)
    if hosted is not None:
        return f"{hosted.host}/{hosted.repo}"

    local = value.strip().rstrip("/")
    if local.endswith(".git"):
        local = local[: -len(".git")]
    return str(Path(local).expanduser().resolve(strict=False))


def git_remotes_match(left: str, right: str) -> bool:
    """Return whether two Git remotes identify the same repository."""

    return _git_remote_identity(left) == _git_remote_identity(right)


def canonical_ssh_remote(host: str, repo: str) -> str:
    """Return the SSH clone URL shape used by the GitHub provider."""

    normalized_host = host.strip().casefold().rstrip("/")
    normalized_repo = repo.strip().strip("/")
    if normalized_repo.endswith(".git"):
        normalized_repo = normalized_repo[: -len(".git")]
    if ":" in normalized_host:
        return f"ssh://git@{normalized_host}/{normalized_repo}.git"
    return f"git@{normalized_host}:{normalized_repo}.git"
