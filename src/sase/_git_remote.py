"""Small transport-neutral helpers for hosted Git remote URLs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from urllib.parse import quote, urlparse


@dataclass(frozen=True)
class _HostedGitRemote:
    """Host and repository path parsed from a hosted Git remote."""

    host: str
    repo: str


class SidecarRemotePolicyError(ValueError):
    """Raised when recorded sidecar metadata names a forbidden transport."""


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


def github_blob_url(
    remote_url: str,
    *,
    provider: str | None,
    branch: str,
    path: str,
) -> str | None:
    """Return a sanitized GitHub blob URL for an unambiguous repository.

    ``github.com`` is recognized directly. Other hosts require authoritative
    provider metadata naming GitHub, which covers GitHub Enterprise without
    guessing from an arbitrary hosted remote.
    """
    parsed = parse_hosted_git_remote(remote_url)
    if parsed is None or not branch.strip() or not path.strip():
        return None
    provider_is_github = (provider or "").strip().casefold() == "github"
    if _host_name(parsed.host) != "github.com" and not provider_is_github:
        return None
    repo_parts = parsed.repo.split("/")
    if len(repo_parts) != 2 or not all(repo_parts):
        return None
    encoded_repo = "/".join(quote(part, safe="") for part in repo_parts)
    encoded_branch = quote(branch.strip(), safe="")
    encoded_path = quote(path.strip().lstrip("/"), safe="/")
    return f"https://{parsed.host}/{encoded_repo}/blob/{encoded_branch}/{encoded_path}"


def github_commit_url(
    remote_url: str,
    *,
    provider: str | None,
    sha: str,
) -> str | None:
    """Return a sanitized GitHub commit URL for a valid hexadecimal SHA."""

    if re.fullmatch(r"[0-9a-f]{7,64}", sha) is None:
        return None
    parsed = parse_hosted_git_remote(remote_url)
    if parsed is None:
        return None
    provider_is_github = (provider or "").strip().casefold() == "github"
    if _host_name(parsed.host) != "github.com" and not provider_is_github:
        return None
    repo_parts = parsed.repo.split("/")
    if len(repo_parts) != 2 or not all(repo_parts):
        return None
    encoded_repo = "/".join(quote(part, safe="") for part in repo_parts)
    return f"https://{parsed.host}/{encoded_repo}/commit/{sha}"


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


def is_http_git_remote(value: str) -> bool:
    """Return whether *value* is an HTTP(S) Git remote."""

    return urlparse(value.strip()).scheme.casefold() in {"http", "https"}


def enforce_sidecar_remote_policy(
    remote_url: str,
    *,
    provider: str | None,
    host: str | None,
    repo: str,
) -> str:
    """Return an approved sidecar remote or reject forbidden HTTP(S).

    GitHub HTTP(S) records can be migrated without network access because the
    provider, host, and repository identity determine the exact SSH URL. Other
    transports remain provider-owned; only HTTP(S) is categorically refused.
    """

    remote = remote_url.strip()
    if not is_http_git_remote(remote):
        return remote

    parsed = parse_hosted_git_remote(remote)
    provider_is_github = (provider or "").strip().casefold() == "github"
    remote_is_github_dot_com = bool(parsed and parsed.host == "github.com")
    if parsed is not None and (provider_is_github or remote_is_github_dot_com):
        canonical_host = _host_authority(host) if host else parsed.host
        if (
            canonical_host
            and _host_name(canonical_host) == _host_name(parsed.host)
            and _repo_ref_matches(parsed.repo, repo)
        ):
            canonical_repo = repo if "/" in _normalize_repo_ref(repo) else parsed.repo
            return canonical_ssh_remote(canonical_host, canonical_repo)

    raise SidecarRemotePolicyError(
        f"HTTP(S) sidecar remote {remote!r} is not allowed and could not be "
        "canonicalized from its GitHub provider, host, and repository metadata. "
        "Correct the recorded sidecar identity and rerun `sase repo init`; Git "
        "was not invoked."
    )


def _host_authority(value: str) -> str:
    """Normalize a configured host while retaining an explicit SSH port."""

    raw = value.strip().casefold().rstrip("/")
    if "://" in raw:
        parsed = urlparse(raw)
        if parsed.hostname is None:
            return ""
        try:
            port = parsed.port
        except ValueError:
            return ""
        return f"{parsed.hostname}:{port}" if port is not None else parsed.hostname
    authority = raw.rsplit("@", 1)[-1].split("/", 1)[0]
    return authority


def _host_name(value: str) -> str:
    """Return a host name without a transport-specific port."""

    authority = _host_authority(value)
    if authority.startswith("["):
        closing = authority.find("]")
        return authority[1:closing] if closing >= 0 else authority
    name, separator, port = authority.rpartition(":")
    return name if separator and port.isdigit() else authority


def _normalize_repo_ref(value: str) -> str:
    normalized = value.strip().strip("/")
    if normalized.endswith(".git"):
        normalized = normalized[: -len(".git")]
    return normalized


def _repo_ref_matches(remote_repo: str, recorded_repo: str) -> bool:
    remote = _normalize_repo_ref(remote_repo).casefold()
    recorded = _normalize_repo_ref(recorded_repo).casefold()
    if not remote or not recorded:
        return False
    if "/" not in recorded:
        return remote.rsplit("/", 1)[-1] == recorded
    return remote == recorded
