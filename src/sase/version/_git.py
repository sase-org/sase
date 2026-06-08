"""Git probing helpers for runtime version inventory."""

from __future__ import annotations

import subprocess
from pathlib import Path

from sase.version._models import GitProbe, GitProbeResult, GitVersionMetadata

_GIT_TIMEOUT_SECONDS = 1.0


def probe_git_metadata(source_root: Path) -> GitProbeResult:
    """Probe git state for ``source_root`` with short timeouts.

    Git failures are represented as warnings so inventory collection remains
    useful in non-git, wheel, or broken-git environments.
    """
    try:
        git_root_text = run_git(source_root, "rev-parse", "--show-toplevel")
        git_root = Path(git_root_text)
        commit = run_git(git_root, "rev-parse", "HEAD")
        short_commit = run_git(git_root, "rev-parse", "--short=9", "HEAD")
        dirty = bool(run_git(git_root, "status", "--porcelain"))
    except FileNotFoundError:
        return GitProbeResult(None, "git is not available on PATH")
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
            "HEAD",
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        tag = None

    if tag:
        try:
            distance = int(run_git(git_root, "rev-list", "--count", f"{tag}..HEAD"))
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


def run_git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_SECONDS,
    )
    return completed.stdout.strip()
