"""Resolve revision-pin rebase conflicts mechanically.

A ``repos.linked[].revision_pin`` file holds one 40-hex SHA naming the pinned
sibling's pushed commit. When a rebase conflicts only because both sides moved
that pin, ancestry in the sibling checkout proves the answer: the descendant
wins. Anything else (diverged, missing, malformed, unreadable) fails closed so
the chain falls through to today's model repair unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess

from sase.bead.conflict_resolver_git import (
    GitProbeFailure,
    git_add,
    read_git_show,
)

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_FETCH_TIMEOUT_SECONDS = 30.0
_GIT_TIMEOUT_SECONDS = 30.0

SiblingDirs = Mapping[str, str | Path]


@dataclass(frozen=True)
class _RevisionPinConflictResolution:
    ok: bool
    message: str
    resolved_files: tuple[str, ...] = ()


def _is_pin_sha(value: str) -> bool:
    """Return whether *value* is a full 40-character hex SHA."""

    return bool(_SHA_RE.match(value.strip()))


def _pins_for_repo(
    repo_root: Path,
    pins: Mapping[str, str] | None,
) -> dict[str, str]:
    """Return ``{linked repo name: normalized pin path}`` for *repo_root*."""

    if pins is not None:
        return dict(pins)
    try:
        from sase.finalizers.commit_revision_pin import revision_pins_for_project
    except Exception:  # noqa: BLE001 - config must never fail resolution
        return {}
    try:
        return dict(revision_pins_for_project(str(repo_root)))
    except Exception:  # noqa: BLE001 - config must never fail resolution
        return {}


def _name_for_path(
    repo_root: Path,
    path: str,
    pins: Mapping[str, str] | None,
) -> str | None:
    """Return the linked-repo name whose pin file is *path*, if any."""

    try:
        pins_map = _pins_for_repo(repo_root, pins)
    except Exception:  # noqa: BLE001 - leave ambiguous paths to the generic gate
        return None
    for name, pin_path in pins_map.items():
        if pin_path == path:
            return name
    return None


def is_revision_pin_conflict_path(
    repo_root: Path,
    path: str,
    *,
    pins: Mapping[str, str] | None = None,
) -> bool:
    """Return whether *path* is a configured revision-pin file."""

    try:
        return _name_for_path(repo_root, path, pins) is not None
    except Exception:  # noqa: BLE001 - leave ambiguous paths to the generic gate.
        return False


def resolve_revision_pin_conflicts(
    repo_root: Path,
    paths: tuple[str, ...],
    *,
    sibling_dirs: SiblingDirs | None = None,
    pins: Mapping[str, str] | None = None,
    fetch_timeout_seconds: float = _FETCH_TIMEOUT_SECONDS,
) -> _RevisionPinConflictResolution:
    """Resolve preclaimed revision-pin conflicts via sibling ancestry."""

    if not paths:
        return _RevisionPinConflictResolution(True, "no revision-pin conflicts")

    pins_map = _pins_for_repo(repo_root, pins)
    pin_owner = {pin_path: name for name, pin_path in pins_map.items()}

    prepared: list[tuple[str, str]] = []
    for path in sorted(paths):
        owner = pin_owner.get(path)
        if owner is None:
            return _RevisionPinConflictResolution(
                False,
                "unsupported revision-pin conflicts: " + path,
            )
        try:
            result = _prepare_pin_resolution(
                repo_root,
                path,
                owner,
                sibling_dirs=sibling_dirs,
                pins=pins,
                fetch_timeout_seconds=fetch_timeout_seconds,
            )
        except GitProbeFailure as error:
            return _RevisionPinConflictResolution(
                False,
                f"revision-pin conflict in {path}: {error}",
            )
        except Exception as error:  # noqa: BLE001 - fail closed to model repair
            return _RevisionPinConflictResolution(
                False,
                f"revision-pin conflict in {path}: {error}",
            )
        if not result[0]:
            return _RevisionPinConflictResolution(False, result[1])
        assert result[2] is not None
        prepared.append((path, result[2]))

    for path, content in prepared:
        target = repo_root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content + "\n", encoding="utf-8")
    git_add(repo_root, [path for path, _content in prepared])
    resolved = tuple(path for path, _content in prepared)
    return _RevisionPinConflictResolution(
        True,
        "resolved revision-pin conflicts: " + ", ".join(resolved),
        resolved,
    )


def _prepare_pin_resolution(
    repo_root: Path,
    path: str,
    owner: str,
    *,
    sibling_dirs: SiblingDirs | None,
    pins: Mapping[str, str] | None,
    fetch_timeout_seconds: float,
) -> tuple[bool, str, str | None]:
    """Decide the winning SHA for *path*; ``(ok, message, sha)``."""

    try:
        raw_a = read_git_show(repo_root, 2, path)
    except GitProbeFailure as error:
        return (False, f"revision-pin conflict in {path}: {error}", None)
    try:
        raw_b = read_git_show(repo_root, 3, path)
    except GitProbeFailure as error:
        return (False, f"revision-pin conflict in {path}: {error}", None)

    sha_a = raw_a.strip()
    sha_b = raw_b.strip()
    if not _is_pin_sha(sha_a):
        return (
            False,
            f"revision-pin conflict in {path}: stage 2 is not a 40-hex SHA",
            None,
        )
    if not _is_pin_sha(sha_b):
        return (
            False,
            f"revision-pin conflict in {path}: stage 3 is not a 40-hex SHA",
            None,
        )
    if sha_a == sha_b:
        return (True, "resolved", sha_a)

    sibling_dir = _resolve_sibling_dir(repo_root, owner, sibling_dirs)
    if sibling_dir is None:
        return (
            False,
            f"revision-pin conflict in {path}: missing sibling checkout "
            f"for linked repo '{owner}'",
            None,
        )
    if not sibling_dir.is_dir():
        return (
            False,
            f"revision-pin conflict in {path}: missing sibling checkout "
            f"for linked repo '{owner}'",
            None,
        )

    if not _sha_present(sibling_dir, sha_a) or not _sha_present(sibling_dir, sha_b):
        _fetch_once(sibling_dir, timeout_seconds=fetch_timeout_seconds)
        if not _sha_present(sibling_dir, sha_a):
            return (
                False,
                f"revision-pin conflict in {path}: SHA {sha_a[:12]} not found "
                f"in sibling checkout for linked repo '{owner}'",
                None,
            )
        if not _sha_present(sibling_dir, sha_b):
            return (
                False,
                f"revision-pin conflict in {path}: SHA {sha_b[:12]} not found "
                f"in sibling checkout for linked repo '{owner}'",
                None,
            )

    try:
        a_ancestor_b = _is_ancestor(sibling_dir, sha_a, sha_b)
    except RuntimeError as error:
        return (False, f"revision-pin conflict in {path}: {error}", None)
    try:
        b_ancestor_a = _is_ancestor(sibling_dir, sha_b, sha_a)
    except RuntimeError as error:
        return (False, f"revision-pin conflict in {path}: {error}", None)

    if a_ancestor_b and not b_ancestor_a:
        return (True, "resolved", sha_b)
    if b_ancestor_a and not a_ancestor_b:
        return (True, "resolved", sha_a)
    if a_ancestor_b and b_ancestor_a:
        # Only reachable when the SHAs are equal; handled above.
        return (True, "resolved", sha_a)
    return (
        False,
        f"revision-pin conflict in {path}: SHAs {sha_a[:12]} and {sha_b[:12]} "
        "diverged (neither is an ancestor of the other)",
        None,
    )


def _resolve_sibling_dir(
    repo_root: Path,
    owner: str,
    sibling_dirs: SiblingDirs | None,
) -> Path | None:
    """Return the local checkout for linked repo *owner*, if known."""

    if sibling_dirs is not None:
        candidate = sibling_dirs.get(owner)
        if candidate is None:
            return None
        return Path(candidate)
    try:
        from sase.llm_provider.commit_finalizer_state._sibling_targets import (
            configured_sibling_targets,
        )
    except Exception:  # noqa: BLE001 - fail closed to model repair
        return None
    try:
        targets = configured_sibling_targets(str(repo_root))
    except Exception:  # noqa: BLE001 - fail closed to model repair
        return None
    for target in targets:
        if target.name == owner:
            return Path(target.workspace_dir)
    return None


def _run_git(
    cwd: Path,
    args: list[str],
    *,
    timeout_seconds: float = _GIT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


def _sha_present(sibling_dir: Path, sha: str) -> bool:
    try:
        result = _run_git(sibling_dir, ["cat-file", "-e", f"{sha}^{{commit}}"])
    except Exception:  # noqa: BLE001 - a probe failure reads as absent
        return False
    return result.returncode == 0


def _fetch_once(sibling_dir: Path, *, timeout_seconds: float) -> None:
    try:
        _run_git(sibling_dir, ["fetch", "origin"], timeout_seconds=timeout_seconds)
    except Exception:  # noqa: BLE001 - fetch failure means try ancestry anyway
        return


def _is_ancestor(sibling_dir: Path, old: str, new: str) -> bool:
    """Return whether *old* is an ancestor of *new* in *sibling_dir*."""

    try:
        result = _run_git(sibling_dir, ["merge-base", "--is-ancestor", old, new])
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"could not test ancestry in sibling checkout: {error}"
        ) from error
    except OSError as error:
        raise RuntimeError(
            f"could not test ancestry in sibling checkout: {error}"
        ) from error
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    detail = (result.stderr or result.stdout or "").strip()
    if detail:
        raise RuntimeError(f"could not test ancestry in sibling checkout: {detail}")
    raise RuntimeError(
        f"could not test ancestry in sibling checkout (exit {result.returncode})"
    )


__all__ = [
    "is_revision_pin_conflict_path",
    "resolve_revision_pin_conflicts",
]
