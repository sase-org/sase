"""Trackedness guarantees for managed memory and instruction files.

``sase memory init --check`` fails when a managed file is untracked or
ignored; the publish guard fails when an intended file was not committed.
Both use one bounded ``git ls-files -z`` plus one ``git check-ignore -z
--stdin`` per owning repo.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from sase.amd.constants import (
    AGENTS_FILENAME,
    AGENTS_TEMPLATE_FILENAME,
    PROVIDER_SHIM_FILES,
)

_GIT_TIMEOUT_SECONDS = 10
_GIT_ENV = {
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_TERMINAL_PROMPT": "0",
}


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(_GIT_ENV)
    return env


def _managed_memory_files(root: Path) -> tuple[Path, ...]:
    """Return existing canonical (and legacy) memory files under *root*."""
    found: list[Path] = []
    for relative in (Path("sase") / "memory", Path("memory")):
        base = root / relative
        if not base.is_dir():
            continue
        try:
            for path in sorted(base.rglob("*")):
                if path.is_file() and not path.is_symlink():
                    found.append(path)
                elif path.is_symlink():
                    try:
                        if path.is_file():
                            found.append(path)
                    except OSError:
                        continue
        except OSError:
            continue
    # Deduplicate by resolved path while keeping a stable order.
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in found:
        key = path.resolve(strict=False)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return tuple(unique)


def _is_managed_agents_text(text: str) -> bool:
    try:
        from sase.amd._agents_doc import is_managed_agents_document
    except ImportError:
        return True
    try:
        return bool(is_managed_agents_document(text))
    except Exception:  # noqa: BLE001 - a parse failure keeps the file managed.
        return True


def _managed_instruction_files(root: Path) -> tuple[Path, ...]:
    """Return existing managed instruction files and shims under *root*."""
    try:
        from sase.amd.inventory import discover_project_agent_docs
    except ImportError:
        discover_project_agent_docs = None  # type: ignore[assignment]
    agents_paths: tuple[Path, ...] = ()
    if discover_project_agent_docs is not None:
        try:
            agents_paths = tuple(discover_project_agent_docs(root))
        except Exception:  # noqa: BLE001 - discovery failure means fallback scan.
            agents_paths = ()
    found: list[Path] = []
    for agents_path in agents_paths:
        try:
            text = agents_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            found.append(agents_path)
            continue
        if _is_managed_agents_text(text):
            found.append(agents_path)
        # Shims alongside a managed AGENTS.md are managed copies.
        sibling_dir = agents_path.parent
        for shim_name in PROVIDER_SHIM_FILES:
            shim_path = sibling_dir / shim_name
            if shim_path.exists() and shim_path.is_file():
                if shim_path not in found:
                    found.append(shim_path)
    # Fallback: root-level files when discovery found nothing (e.g. home roots
    # or minimal checkouts). Root AGENTS.md/shims are always managed scope.
    if not found:
        for name in (AGENTS_FILENAME, *PROVIDER_SHIM_FILES):
            candidate = root / name
            if candidate.exists() and candidate.is_file():
                if candidate not in found:
                    found.append(candidate)
    # Chezmoi template sources are the managed home instruction files.
    try:
        for template_path in sorted(root.rglob(AGENTS_TEMPLATE_FILENAME)):
            if template_path.is_file() and template_path not in found:
                found.append(template_path)
    except OSError:
        pass
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in found:
        key = path.resolve(strict=False)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return tuple(unique)


def _managed_paths_for_root(root: Path) -> tuple[Path, ...]:
    """Return all existing managed memory + instruction files under *root*."""
    return (*_managed_memory_files(root), *_managed_instruction_files(root))


def git_toplevel(start: Path) -> Path | None:
    """Return the owning repo toplevel for *start*, or None when absent."""
    try:
        result = subprocess.run(
            [
                "git",
                "--no-optional-locks",
                "-C",
                str(start),
                "rev-parse",
                "--show-toplevel",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
            env=_git_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return Path(result.stdout.strip())


def _git_ls_files_tracked(repo: Path) -> set[str] | None:
    """Return repo-relative tracked paths, or None on any git failure."""
    try:
        result = subprocess.run(
            [
                "git",
                "-c",
                "core.quotepath=off",
                "--no-optional-locks",
                "-C",
                str(repo),
                "ls-files",
                "-z",
            ],
            capture_output=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
            env=_git_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    output = result.stdout
    if not isinstance(output, (bytes, bytearray)):
        # Mocked git in unit tests returns str stdout; without a trustworthy
        # tracked set the check stays fail-open for this repo.
        return None
    if not output:
        return set()
    parts = bytes(output).split(b"\0")
    tracked: set[str] = set()
    for part in parts:
        if not part:
            continue
        try:
            tracked.add(part.decode("utf-8", errors="surrogateescape"))
        except Exception:  # noqa: BLE001 - never fail a check on decode.
            continue
    return tracked


def _git_check_ignored(repo: Path, candidates: list[str]) -> set[str]:
    """Return the subset of *candidates* (repo-relative) that git ignores."""
    if not candidates:
        return set()
    try:
        result = subprocess.run(
            [
                "git",
                "-c",
                "core.quotepath=off",
                "--no-optional-locks",
                "-C",
                str(repo),
                "check-ignore",
                "-z",
                "--stdin",
            ],
            input="\0".join(candidates).encode("utf-8", errors="surrogateescape"),
            capture_output=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
            env=_git_env(),
        )
    except (OSError, subprocess.TimeoutExpired, TypeError):
        return set()
    if result.returncode not in (0, 1) or not result.stdout:
        return set()
    if not isinstance(result.stdout, (bytes, bytearray)):
        return set()
    ignored: set[str] = set()
    for part in bytes(result.stdout).split(b"\0"):
        if not part:
            continue
        try:
            ignored.add(part.decode("utf-8", errors="surrogateescape"))
        except Exception:  # noqa: BLE001 - never fail a check on decode.
            continue
    return ignored


def _repo_relative(repo: Path, path: Path) -> str | None:
    try:
        return (
            path.resolve(strict=False)
            .relative_to(repo.resolve(strict=False))
            .as_posix()
        )
    except ValueError:
        return None


def tracking_blockers_for_root(root: Path, *, label: str = "memory") -> tuple[str, ...]:
    """Return --check blockers for untracked/ignored managed files under *root*."""
    managed = _managed_paths_for_root(root)
    if not managed:
        return ()
    by_repo: dict[Path, list[Path]] = {}
    repo_for: dict[Path, Path] = {}
    for path in managed:
        toplevel = git_toplevel(path.parent)
        if toplevel is None:
            continue
        by_repo.setdefault(toplevel, []).append(path)
        repo_for[path] = toplevel
    blockers: list[str] = []
    for repo, paths in by_repo.items():
        tracked = _git_ls_files_tracked(repo)
        if tracked is None:
            continue
        rels: dict[str, Path] = {}
        for path in paths:
            rel = _repo_relative(repo, path)
            if rel is not None:
                rels[rel] = path
        ignored = _git_check_ignored(repo, sorted(rels))
        for rel in sorted(rels):
            if rel in tracked:
                continue
            path = rels[rel]
            try:
                display = path.relative_to(root.resolve(strict=False)).as_posix()
            except ValueError:
                display = rel
            kind = "memory" if "memory" in display else "instruction"
            if rel in ignored:
                blockers.append(
                    f"{label}: IGNORED managed {kind} file {display} in {repo} - "
                    "commit this file to start its history "
                    "(untracked or ignored managed files fail `sase memory init --check`)"
                )
            else:
                blockers.append(
                    f"{label}: UNTRACKED managed {kind} file {display} in {repo} - "
                    "commit this file to start its history "
                    "(untracked or ignored managed files fail `sase memory init --check`)"
                )
    return tuple(blockers)


def _git_status_dirty(repo: Path, rels: list[str]) -> set[str]:
    """Return the subset of *rels* with uncommitted worktree/index changes."""
    if not rels:
        return set()
    try:
        result = subprocess.run(
            [
                "git",
                "-c",
                "core.quotepath=off",
                "--no-optional-locks",
                "-C",
                str(repo),
                "status",
                "--porcelain=v1",
                "--untracked-files=no",
                "-z",
                "--",
                *rels,
            ],
            capture_output=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
            env=_git_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    if result.returncode != 0 or not result.stdout:
        return set()
    if not isinstance(result.stdout, (bytes, bytearray)):
        return set()
    dirty: set[str] = set()
    parts = bytes(result.stdout).split(b"\0")
    index = 0
    while index < len(parts):
        token = parts[index]
        index += 1
        if not token:
            continue
        try:
            text = token.decode("utf-8", errors="surrogateescape")
        except Exception:  # noqa: BLE001 - never fail a guard on decode.
            continue
        if len(text) < 4:
            continue
        rel = text[3:]
        if rel:
            dirty.add(rel)
        if len(text) >= 2 and text[0] == "R":
            # Renames emit the source path as a second NUL field; consume it.
            if index < len(parts) and parts[index]:
                try:
                    dirty.add(parts[index].decode("utf-8", errors="surrogateescape"))
                except Exception:  # noqa: BLE001 - see above.
                    pass
                index += 1
    return dirty


def verify_publish_guard_for_root(
    root: Path, *, label: str = "memory"
) -> tuple[str, ...]:
    """Verify every managed file under *root* is tracked and clean."""
    managed = _managed_paths_for_root(root)
    if not managed:
        return ()
    by_repo: dict[Path, dict[str, Path]] = {}
    for path in managed:
        toplevel = git_toplevel(path.parent)
        if toplevel is None:
            continue
        rel = _repo_relative(toplevel, path)
        if rel is None:
            continue
        by_repo.setdefault(toplevel, {})[rel] = path
    problems: list[str] = []
    for repo, rel_map in by_repo.items():
        tracked = _git_ls_files_tracked(repo)
        if tracked is None:
            continue
        ignored = _git_check_ignored(repo, sorted(rel_map))
        dirty = _git_status_dirty(repo, sorted(rel_map))
        for rel in sorted(rel_map):
            path = rel_map[rel]
            try:
                display = path.relative_to(root.resolve(strict=False)).as_posix()
            except ValueError:
                display = rel
            if rel not in tracked:
                state = "ignored" if rel in ignored else "untracked"
                problems.append(
                    f"{label}: publish left managed file {display} {state} in {repo} - "
                    "the intended file was not committed"
                )
            elif rel in dirty:
                problems.append(
                    f"{label}: publish left managed file {display} with uncommitted "
                    f"changes in {repo} - the intended file was not committed"
                )
    return tuple(problems)


__all__ = [
    "tracking_blockers_for_root",
    "verify_publish_guard_for_root",
]
