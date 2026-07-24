"""Read untrusted agents payloads from one fetched commit without checkout."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re

from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.v2_io import validate_relative_path

_SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


@dataclass(frozen=True, slots=True)
class FetchedAgentsCommit:
    """An exact local remote-tracking ref and the commit it resolved to."""

    ref: str
    sha: str


class LocalGitObjectReader:
    """Injectable local-only Git object reader.

    Every command is explicitly marked non-network. The reader never invokes
    checkout-like commands and therefore cannot alter HEAD, the index, or the
    sidecar worktree.
    """

    def __init__(
        self,
        repo: Path,
        *,
        git_runner: GitRunner = run_git,
    ) -> None:
        self.repo = repo
        self.git_runner = git_runner

    def resolve_fetched_commit(self) -> FetchedAgentsCommit:
        upstream = self.git_runner(
            self.repo,
            ["rev-parse", "--symbolic-full-name", "@{upstream}"],
            op="agents_sync.object_upstream_ref",
        )
        if upstream.returncode != 0:
            raise AgentsSyncFormatError(
                _git_error("agents sidecar has no configured upstream", upstream)
            )
        ref = upstream.stdout.strip()
        if not _valid_fetched_ref(ref):
            raise AgentsSyncFormatError(f"unsafe fetched upstream ref: {ref!r}")
        resolved = self.git_runner(
            self.repo,
            ["rev-parse", "--verify", f"{ref}^{{commit}}"],
            op="agents_sync.object_upstream_sha",
        )
        sha = resolved.stdout.strip().lower()
        if resolved.returncode != 0 or _SHA_RE.fullmatch(sha) is None:
            raise AgentsSyncFormatError(
                _git_error("could not resolve fetched upstream commit", resolved)
            )
        return FetchedAgentsCommit(ref, sha)

    def manifest_paths(self, sha: str) -> tuple[str, ...]:
        _validate_sha(sha)
        result = self.git_runner(
            self.repo,
            [
                "ls-tree",
                "-r",
                "--name-only",
                "-z",
                sha,
                "--",
                "manifest.json",
                "users",
            ],
            op="agents_sync.object_manifest_paths",
        )
        if result.returncode != 0:
            raise AgentsSyncFormatError(
                _git_error("could not list fetched agents manifests", result)
            )
        paths: list[str] = []
        for raw in result.stdout.split("\x00"):
            if not raw:
                continue
            parts = PurePosixPath(raw).parts
            is_owner_manifest = (
                len(parts) == 5
                and parts[0] == "users"
                and parts[2] == "machines"
                and parts[4] == "manifest.json"
            )
            if raw != "manifest.json" and not is_owner_manifest:
                continue
            paths.append(validate_relative_path(raw))
        return tuple(sorted(set(paths)))

    def read_bytes(self, sha: str, relative: str, *, maximum: int) -> bytes:
        _validate_sha(sha)
        validate_relative_path(relative)
        result = self.git_runner(
            self.repo,
            ["show", f"{sha}:{relative}"],
            op="agents_sync.object_read",
        )
        if result.returncode != 0:
            raise AgentsSyncFormatError(
                _git_error(f"could not read fetched object {relative!r}", result)
            )
        try:
            payload = result.stdout.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise AgentsSyncFormatError(
                f"fetched object {relative!r} is not valid UTF-8"
            ) from exc
        if len(payload) > maximum:
            raise AgentsSyncFormatError(
                f"fetched object {relative!r} exceeds the byte limit"
            )
        return payload


def _validate_sha(value: str) -> None:
    if _SHA_RE.fullmatch(value) is None:
        raise AgentsSyncFormatError(f"invalid fetched commit SHA: {value!r}")


def _valid_fetched_ref(value: str) -> bool:
    return (
        value.startswith("refs/remotes/")
        and len(value.encode("utf-8")) <= 1024
        and not any(ord(char) <= 32 or char in "~^:?*[\\" for char in value)
        and ".." not in value
        and not value.endswith((".", "/"))
    )


def _git_error(prefix: str, result: object) -> str:
    stderr = getattr(result, "stderr", "")
    stdout = getattr(result, "stdout", "")
    detail = (stderr or stdout or "unknown git error").strip()
    return f"{prefix}: {detail}"


__all__ = ["FetchedAgentsCommit", "LocalGitObjectReader"]
