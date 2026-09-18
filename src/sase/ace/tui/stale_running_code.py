"""Detect when editable code imported by this ACE process has moved on disk."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from sase.updates import CommitSourceSpec, IncomingCommits, fetch_incoming_commits
from sase.version.inventory import collect_runtime_version_inventory
from sase.version._git import run_git

_INCOMING_LIMIT = 5

HeadResolver = Callable[[str], str]
IncomingFetcher = Callable[..., IncomingCommits]


@dataclass(frozen=True, slots=True)
class _GitStatToken:
    """Cheap filesystem token for deciding whether HEAD needs re-reading."""

    head: tuple[int, int] | None
    packed_refs: tuple[int, int] | None


@dataclass(frozen=True, slots=True)
class RunningCodeRoot:
    """One editable git checkout imported by the running TUI process."""

    label: str
    git_root: str
    imported_sha: str
    current_sha: str
    git_dir: str
    head_path: str
    packed_refs_path: str
    token: _GitStatToken
    incoming: IncomingCommits | None = None

    @property
    def is_stale(self) -> bool:
        """Return whether this checkout has advanced since import capture."""
        return self.current_sha != self.imported_sha


@dataclass(frozen=True, slots=True)
class RunningCodeState:
    """Cached stale-running-code status for this TUI process."""

    roots: tuple[RunningCodeRoot, ...] = ()

    @property
    def stale_roots(self) -> tuple[RunningCodeRoot, ...]:
        """Return roots whose on-disk HEAD differs from the imported SHA."""
        return tuple(root for root in self.roots if root.is_stale)

    @property
    def stale_signature(self) -> tuple[tuple[str, str], ...]:
        """Stable generation key for one-time stale-code notifications."""
        return tuple(
            (root.git_root, root.current_sha)
            for root in self.stale_roots
            if root.current_sha
        )

    @property
    def is_stale(self) -> bool:
        """Return whether any imported checkout has moved on disk."""
        return bool(self.stale_roots)


def _capture_running_code_state(
    *,
    inventory_fn: Callable[[], Any] | None = None,
) -> RunningCodeState:
    """Capture editable runtime git roots and their imported HEAD SHAs.

    Missing, non-editable, and non-git roots simply do not enter the tracked
    set. The caller runs this in a worker thread after first paint.
    """
    if inventory_fn is None:

        def inventory_fn() -> Any:
            return collect_runtime_version_inventory(include_plugins=True)

    try:
        inventory = inventory_fn()
    except Exception:  # noqa: BLE001 - stale-code hints must never break startup.
        return RunningCodeState()

    grouped: dict[str, tuple[set[str], str]] = {}
    for record in getattr(inventory, "packages", ()):
        if getattr(record, "install_type", None) != "editable":
            continue
        if getattr(record, "role", None) not in {"host", "core", "plugin"}:
            continue
        git = getattr(record, "git", None)
        git_root = getattr(git, "root", None)
        imported_sha = getattr(git, "commit", None)
        if not git_root or not imported_sha:
            continue
        labels, first_sha = grouped.setdefault(
            str(git_root), (set(), str(imported_sha))
        )
        labels.add(str(getattr(record, "name", None) or git_root))
        if first_sha != str(imported_sha):
            grouped[str(git_root)] = (labels, first_sha)

    roots: list[RunningCodeRoot] = []
    for git_root, (labels, imported_sha) in sorted(grouped.items()):
        paths = _resolve_git_paths(Path(git_root))
        if paths is None:
            continue
        git_dir, head_path, packed_refs_path = paths
        roots.append(
            RunningCodeRoot(
                label=_format_label(labels),
                git_root=git_root,
                imported_sha=imported_sha,
                current_sha=imported_sha,
                git_dir=str(git_dir),
                head_path=str(head_path),
                packed_refs_path=str(packed_refs_path),
                token=_stat_token(head_path, packed_refs_path),
            )
        )
    return RunningCodeState(roots=tuple(roots))


def _revalidate_running_code_state(
    state: RunningCodeState,
    *,
    head_fn: HeadResolver | None = None,
    fetch_incoming_fn: IncomingFetcher | None = None,
) -> RunningCodeState:
    """Refresh cached running-code state using stat-gated git HEAD reads."""
    if head_fn is None:
        head_fn = _resolve_head_sha
    if fetch_incoming_fn is None:
        fetch_incoming_fn = fetch_incoming_commits

    changed = False
    roots: list[RunningCodeRoot] = []
    for root in state.roots:
        token = _stat_token(Path(root.head_path), Path(root.packed_refs_path))
        if token == root.token:
            roots.append(root)
            continue

        changed = True
        try:
            current_sha = head_fn(root.git_root)
        except Exception:  # noqa: BLE001 - retain previous evidence on git failures.
            roots.append(replace(root, token=token))
            continue

        incoming: IncomingCommits | None = None
        if current_sha != root.imported_sha:
            incoming = _fetch_incoming(root, current_sha, fetch_fn=fetch_incoming_fn)
        roots.append(
            replace(
                root,
                current_sha=current_sha,
                token=token,
                incoming=incoming,
            )
        )

    if not changed:
        return state
    return RunningCodeState(roots=tuple(roots))


def refresh_running_code_state(
    state: RunningCodeState | None,
) -> RunningCodeState:
    """Capture once, then revalidate the captured roots on later checks."""
    if state is None:
        return _capture_running_code_state()
    return _revalidate_running_code_state(state)


def _fetch_incoming(
    root: RunningCodeRoot,
    current_sha: str,
    *,
    fetch_fn: IncomingFetcher,
) -> IncomingCommits:
    spec = CommitSourceSpec(
        source="git",
        repo_full_name=root.label,
        git_root=root.git_root,
        current_ref=root.imported_sha,
        upstream_ref=current_sha,
    )
    return fetch_fn(spec, limit=_INCOMING_LIMIT)


def _resolve_head_sha(git_root: str) -> str:
    return run_git(Path(git_root), "rev-parse", "HEAD")


def _resolve_git_paths(root: Path) -> tuple[Path, Path, Path] | None:
    dot_git = root / ".git"
    git_dir = _resolve_git_dir(dot_git, root)
    if git_dir is None:
        return None
    common_dir = _resolve_common_git_dir(git_dir)
    head_file = git_dir / "HEAD"
    head_path = head_file
    try:
        text = head_file.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        text = ""
    head_kind, sep, raw_ref = text.partition(":")
    if head_kind == "ref" and sep:
        ref = raw_ref.strip()
        if ref:
            common_ref = common_dir / ref
            head_path = common_ref if common_ref.exists() else git_dir / ref
    return git_dir, head_path, common_dir / "packed-refs"


def _resolve_git_dir(dot_git: Path, root: Path) -> Path | None:
    if dot_git.is_dir():
        return dot_git
    if not dot_git.is_file():
        return None
    try:
        text = dot_git.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    prefix = "gitdir:"
    if not text.lower().startswith(prefix):
        return None
    raw = text[len(prefix) :].strip()
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    return path.resolve(strict=False)


def _resolve_common_git_dir(git_dir: Path) -> Path:
    try:
        raw = (
            (git_dir / "commondir")
            .read_text(encoding="utf-8", errors="replace")
            .strip()
        )
    except OSError:
        return git_dir
    if not raw:
        return git_dir
    path = Path(raw)
    if not path.is_absolute():
        path = git_dir / path
    return path.resolve(strict=False)


def _stat_token(head_path: Path, packed_refs_path: Path) -> _GitStatToken:
    return _GitStatToken(
        head=_stat_signature(head_path),
        packed_refs=_stat_signature(packed_refs_path),
    )


def _stat_signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (int(stat.st_mtime_ns), int(stat.st_size))


def _format_label(labels: set[str]) -> str:
    names = tuple(sorted(labels, key=str.casefold))
    if not names:
        return "checkout"
    if len(names) == 1:
        return names[0]
    return f"{names[0]} + {len(names) - 1} more"


__all__ = [
    "RunningCodeRoot",
    "RunningCodeState",
    "refresh_running_code_state",
]
