"""Git probing helpers for runtime version inventory."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sase.git_lock_retry import run_with_git_lock_retry
from sase.workspace_provider.utils import non_interactive_git_env
from sase.version._models import GitProbe, GitProbeResult, GitVersionMetadata

_GIT_TIMEOUT_SECONDS = 1.0
_GIT_MUTATE_TIMEOUT_SECONDS = 120.0

SubprocessRun = Callable[..., subprocess.CompletedProcess[str]]
GitTextRun = Callable[..., str]


@dataclass(frozen=True)
class GitUpstreamStatus:
    """HEAD-vs-upstream state for one checkout."""

    root: str
    upstream: str | None
    remote: str | None
    remote_branch: str | None
    detached: bool
    dirty: bool
    ahead: int | None
    behind: int | None

    @property
    def has_upstream(self) -> bool:
        return self.upstream is not None

    @property
    def diverged(self) -> bool:
        return bool(self.ahead and self.behind)

    @property
    def strictly_behind(self) -> bool:
        return self.ahead == 0 and self.behind is not None and self.behind > 0

    @property
    def up_to_date(self) -> bool:
        return self.ahead == 0 and self.behind == 0


def probe_git_metadata(source_root: Path) -> GitProbeResult:
    """Probe git state for ``source_root`` with short timeouts.

    Git failures are represented as warnings so inventory collection remains
    useful in non-git, wheel, or broken-git environments.
    """
    return probe_git_metadata_at_ref(source_root, "HEAD")


def probe_git_metadata_at_ref(source_root: Path, ref: str = "HEAD") -> GitProbeResult:
    """Probe git version metadata for ``source_root`` at an arbitrary ref."""
    try:
        git_root_text = run_git(source_root, "rev-parse", "--show-toplevel")
        git_root = Path(git_root_text)
        commit = run_git(git_root, "rev-parse", ref)
        short_commit = run_git(git_root, "rev-parse", "--short=9", ref)
        dirty = ref == "HEAD" and bool(run_git(git_root, "status", "--porcelain"))
    except FileNotFoundError:
        return GitProbeResult(None, "git is not available on PATH")
    except OSError as exc:
        return GitProbeResult(None, f"git could not be executed: {exc}")
    except subprocess.TimeoutExpired:
        return GitProbeResult(None, f"git probe timed out for {source_root}")
    except subprocess.CalledProcessError as exc:
        return GitProbeResult(
            None,
            f"git metadata unavailable for {source_root}: {exc.stderr.strip() or exc}",
        )

    tag: str | None = None
    distance: int | None = None
    try:
        tag = run_git(
            git_root,
            "describe",
            "--tags",
            "--match",
            "v[0-9]*",
            "--abbrev=0",
            ref,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        tag = None

    if tag:
        try:
            distance = int(run_git(git_root, "rev-list", "--count", f"{tag}..{ref}"))
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
            distance = None

    return GitProbeResult(
        GitVersionMetadata(
            root=str(git_root),
            commit=commit,
            short_commit=short_commit,
            tag=tag,
            distance=distance,
            dirty=dirty,
        )
    )


def classify_git_upstream(source_root: Path) -> GitUpstreamStatus:
    """Resolve upstream state and HEAD ancestry for ``source_root``."""
    git_root_text = run_git(source_root, "rev-parse", "--show-toplevel")
    git_root = Path(git_root_text)
    dirty = bool(run_git(git_root, "status", "--porcelain"))

    try:
        branch = run_git(git_root, "symbolic-ref", "--quiet", "--short", "HEAD")
    except subprocess.CalledProcessError:
        return GitUpstreamStatus(
            root=str(git_root),
            upstream=None,
            remote=None,
            remote_branch=None,
            detached=True,
            dirty=dirty,
            ahead=None,
            behind=None,
        )

    try:
        upstream = run_git(
            git_root,
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{upstream}",
        )
    except subprocess.CalledProcessError:
        return GitUpstreamStatus(
            root=str(git_root),
            upstream=None,
            remote=None,
            remote_branch=None,
            detached=False,
            dirty=dirty,
            ahead=None,
            behind=None,
        )

    remote = _optional_git(git_root, "config", "--get", f"branch.{branch}.remote")
    remote_ref = _optional_git(git_root, "config", "--get", f"branch.{branch}.merge")
    remote_branch = _remote_branch_from_ref(remote_ref) or _branch_from_upstream(
        upstream, remote
    )
    ahead, behind = _ahead_behind(git_root, upstream)

    return GitUpstreamStatus(
        root=str(git_root),
        upstream=upstream,
        remote=remote,
        remote_branch=remote_branch,
        detached=False,
        dirty=dirty,
        ahead=ahead,
        behind=behind,
    )


def fetch_git_upstream(
    status: GitUpstreamStatus, *, run_git_fn: GitTextRun | None = None
) -> None:
    """Fetch the resolved upstream for ``status``."""
    runner = run_git if run_git_fn is None else run_git_fn
    root = Path(status.root)
    runner(root, *git_fetch_upstream_args(status), timeout=_GIT_MUTATE_TIMEOUT_SECONDS)


def git_fetch_upstream_args(status: GitUpstreamStatus) -> tuple[str, ...]:
    """Return argv fragments that refresh ``status``'s upstream tracking ref."""
    args = ["fetch", "--quiet", "--tags", "--force"]
    if status.remote and status.remote_branch:
        args.extend([status.remote, _remote_tracking_refspec(status)])
    elif status.remote:
        args.append(status.remote)
    return tuple(args)


def _remote_tracking_refspec(status: GitUpstreamStatus) -> str:
    assert status.remote is not None
    assert status.remote_branch is not None
    return (
        f"+refs/heads/{status.remote_branch}:"
        f"refs/remotes/{status.remote}/{status.remote_branch}"
    )


def merge_git_ff_only(
    root: Path, upstream: str, *, run_git_fn: GitTextRun | None = None
) -> None:
    """Fast-forward ``root`` to ``upstream``."""
    runner = run_git if run_git_fn is None else run_git_fn
    runner(
        root,
        "merge",
        "--ff-only",
        upstream,
        timeout=_GIT_MUTATE_TIMEOUT_SECONDS,
    )


def probe_git(
    source_root: Path | None,
    git_probe: GitProbe | None,
) -> GitProbeResult:
    if source_root is None or git_probe is None:
        return GitProbeResult(None)
    return git_probe(source_root)


def cached_git_probe(git_probe: GitProbe | None) -> GitProbe | None:
    if git_probe is None:
        return None

    cache: dict[Path, GitProbeResult] = {}

    def cached(source_root: Path) -> GitProbeResult:
        cache_key = git_probe_cache_key(source_root)
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            return cached_result

        result = git_probe(source_root)
        cache[cache_key] = result
        if result.metadata is not None:
            git_root_key = git_probe_cache_key(Path(result.metadata.root))
            cache.setdefault(git_root_key, result)
        return result

    return cached


def git_probe_cache_key(source_root: Path) -> Path:
    try:
        return source_root.expanduser().resolve(strict=False)
    except OSError:
        return source_root.expanduser().absolute()


def run_git(
    root: Path,
    *args: str,
    run_fn: SubprocessRun | None = None,
    timeout: float = _GIT_TIMEOUT_SECONDS,
) -> str:
    argv = ["git", "-C", str(root), *args]

    def attempt() -> subprocess.CompletedProcess[str] | subprocess.CalledProcessError:
        try:
            if run_fn is None:
                return subprocess.run(
                    argv,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env=non_interactive_git_env(),
                    stdin=subprocess.DEVNULL,
                )
            return run_fn(
                argv,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.CalledProcessError as exc:
            return exc

    completed, _outcome = run_with_git_lock_retry(
        attempt,
        cwd=root,
        result_adapter=_git_result_adapter,
    )
    if isinstance(completed, subprocess.CalledProcessError):
        raise completed
    return completed.stdout.strip()


def _git_result_adapter(result: object) -> tuple[int, str]:
    returncode = getattr(result, "returncode", 0)
    output = "\n".join(
        value
        for value in (getattr(result, "stderr", None), getattr(result, "stdout", None))
        if isinstance(value, str) and value
    )
    return int(returncode), output


def _optional_git(root: Path, *args: str) -> str | None:
    try:
        value = run_git(root, *args)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return value or None


def _ahead_behind(root: Path, upstream: str) -> tuple[int | None, int | None]:
    try:
        text = run_git(
            root, "rev-list", "--left-right", "--count", f"HEAD...{upstream}"
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None, None
    parts = text.split()
    if len(parts) != 2:
        return None, None
    try:
        ahead = int(parts[0])
        behind = int(parts[1])
    except ValueError:
        return None, None
    return ahead, behind


def _remote_branch_from_ref(remote_ref: str | None) -> str | None:
    prefix = "refs/heads/"
    if remote_ref and remote_ref.startswith(prefix):
        return remote_ref[len(prefix) :]
    return remote_ref


def _branch_from_upstream(upstream: str, remote: str | None) -> str | None:
    if remote and upstream.startswith(f"{remote}/"):
        return upstream[len(remote) + 1 :]
    if "/" in upstream:
        return upstream.split("/", 1)[1]
    return None
