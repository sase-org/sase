"""Shared sidecar publication state, git probes, and clone discovery."""

from dataclasses import dataclass
from pathlib import Path

from sase._linked_repo_paths import (
    EXTERNAL_REPO_CLONES_SUBDIR,
    LINKED_REPO_CLONES_SUBDIR,
    SIDECAR_REPO_CLONES_SUBDIR,
)


@dataclass(frozen=True)
class SidecarPublicationResult:
    published: bool
    detail: str | None = None


@dataclass(frozen=True)
class SidecarUpstreamTarget:
    branch: str
    remote: str


@dataclass(frozen=True)
class SidecarCommitCountResult:
    count: int
    error: str | None = None
    damaged: bool = False


#: Publication failures keyed by ``(repo_root, HEAD sha)``. The eviction pass
#: must not re-publish a sidecar whose publication already failed at the same
#: HEAD earlier in this launch: one publication attempt per sidecar per
#: launch, then rescue. Entries are keyed by HEAD so a genuinely new commit
#: still gets its own publication attempt.
_FAILED_PUBLICATIONS: dict[tuple[str, str], str] = {}


def prior_publication_failure(repo_root: Path, head_sha: str | None) -> str | None:
    """Return the earlier failure detail when this HEAD already failed to publish."""
    if head_sha is None:
        return None
    return _FAILED_PUBLICATIONS.get((str(repo_root), head_sha))


def record_publication_failure(
    repo_root: Path, head_sha: str | None, detail: str
) -> None:
    """Memoize a publication failure so a later pass rescues instead of retrying."""
    if head_sha is None:
        return
    _FAILED_PUBLICATIONS[(str(repo_root), head_sha)] = detail


def current_head_sha(repo_root: Path) -> str | None:
    from sase.sdd._repository_health import default_git_runner

    result = default_git_runner(
        repo_root,
        ["rev-parse", "--verify", "HEAD"],
        op="workspace.sidecar_safety.head_sha",
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def workspace_sidecar_repo_roots(workspace_root: Path) -> list[Path]:
    """Return direct Git sidecar clones under ``sase/repos/<role>``."""
    repos_root = workspace_root.joinpath(*SIDECAR_REPO_CLONES_SUBDIR)
    if not repos_root.is_dir():
        return []

    skipped_containers = {
        LINKED_REPO_CLONES_SUBDIR[-1],
        EXTERNAL_REPO_CLONES_SUBDIR[-1],
    }
    roots: list[Path] = []
    try:
        children = sorted(repos_root.iterdir(), key=lambda path: path.name)
    except OSError:
        return []
    for child in children:
        if child.name in skipped_containers:
            continue
        if not child.is_dir():
            continue
        if not (child / ".git").exists():
            continue
        roots.append(child.resolve())
    return roots
