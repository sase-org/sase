"""Hidden bare partial clones for the attachment sidecar roles.

The attachment stores live in bare ``--filter=blob:none`` clones at the
machine-level hidden path. They have no worktree, so the working-tree clone
machinery (``ensure_sidecar_sdd_clone``) must not manage them: that helper
treats ``(clone / ".git").is_dir()`` as "already cloned", which is false for
a bare repository.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

from sase._git_remote import is_http_git_remote
from sase.sdd._git import network_git_timeout, run_sdd_git, sdd_git_command
from sase.sdd._store_git import git_remote_url as _git_remote_url
from sase.sdd._store_git import same_git_remote as _same_git_remote
from sase.sdd._store_types import (
    ATTACHMENTS_PRIVATE_SIDECAR_ROLE,
    ATTACHMENTS_SIDECAR_ROLE,
    SddMaterializationError,
)

ATTACHMENTS_INIT_COMMIT_MESSAGE = "chore(attachments): initialize private store"
ATTACHMENTS_PUBLIC_INIT_COMMIT_MESSAGE = "chore(attachments): initialize public store"

_BARE_CLONE_ARGS = ("clone", "--bare", "--filter=blob:none")
_LOCAL_PLUMBING_TIMEOUT_SECONDS = 60.0


def is_bare_sidecar_clone(path: Path) -> bool:
    """Return whether *path* looks like a bare git repository clone."""

    return (
        (path / "HEAD").is_file()
        and (path / "objects").is_dir()
        and not (path / ".git").exists()
    )


def ensure_attachments_private_bare_clone(
    clone_dir: Path,
    remote_url: str,
) -> None:
    """Ensure the hidden private bare partial clone exists and has a root commit."""

    ensure_attachments_bare_clone(
        clone_dir, remote_url, role=ATTACHMENTS_PRIVATE_SIDECAR_ROLE
    )


def ensure_attachments_bare_clone(
    clone_dir: Path,
    remote_url: str,
    *,
    role: str = ATTACHMENTS_PRIVATE_SIDECAR_ROLE,
) -> None:
    """Ensure the hidden bare partial clone for *role* exists with a root commit."""

    from sase.sdd._store_git import set_sdd_origin as _set_sdd_origin

    clone_dir = clone_dir.expanduser()
    clone_dir.parent.mkdir(parents=True, exist_ok=True)
    is_public = role == ATTACHMENTS_SIDECAR_ROLE
    if not is_public and is_http_git_remote(remote_url):
        raise SddMaterializationError(
            f"refusing HTTP(S) attachments-private sidecar remote {remote_url!r}; "
            "materialization requires an SSH or local Git remote and Git was "
            "not invoked"
        )
    if os.path.lexists(clone_dir):
        if not is_bare_sidecar_clone(clone_dir):
            raise SddMaterializationError(
                f"refusing to overwrite existing {role} sidecar "
                f"path at {clone_dir}; it is not a bare repository clone"
            )
        current = _bare_remote_url(clone_dir)
        if current is None:
            if is_public:
                _set_public_origin(clone_dir, remote_url)
            else:
                _set_sdd_origin(clone_dir, remote_url)
            current = _bare_remote_url(clone_dir)
        if current is None or not _same_git_remote(current, remote_url):
            # A public clone stores an anonymous HTTPS fetch URL in
            # ``origin`` with the configured remote as ``pushurl``; accept
            # either the fetch URL or the push URL as the expected remote.
            if is_public and _public_origin_matches(clone_dir, remote_url):
                pass
            else:
                raise SddMaterializationError(
                    f"{role} sidecar clone at {clone_dir} has origin "
                    f"{current!r}, expected {remote_url!r}"
                )
    else:
        _clone_bare_partial(clone_dir, remote_url, role=role)
    _ensure_bare_head_commit(clone_dir, role=role)
    if is_public:
        _set_public_origin(clone_dir, remote_url)


def _anonymous_fetch_url(configured_remote: str) -> str | None:
    """Return the anonymous HTTPS fetch URL for *configured_remote*, if mappable."""

    try:
        from sase._git_remote import parse_hosted_git_remote
    except Exception:
        return None
    try:
        parsed = parse_hosted_git_remote(configured_remote)
    except Exception:
        return None
    if parsed is None or not parsed.host or not parsed.repo:
        return None
    return f"https://{parsed.host}/{parsed.repo}.git"


def _set_public_origin(clone_dir: Path, configured_remote: str) -> None:
    """Point a public clone at the anonymous fetch URL with an SSH push URL."""

    fetch_url = _anonymous_fetch_url(configured_remote)
    try:
        if fetch_url is not None:
            _run_bare_git(clone_dir, ["remote", "set-url", "origin", fetch_url])
            _run_bare_git(
                clone_dir, ["remote", "set-url", "--push", "origin", configured_remote]
            )
        else:
            from sase.sdd._store_git import set_sdd_origin as _set_sdd_origin

            _set_sdd_origin(clone_dir, configured_remote)
            # No separate push URL when the remote is not mappable.
            _run_bare_git(clone_dir, ["config", "--unset", "remote.origin.pushurl"])
    except Exception:
        pass


def _public_origin_matches(clone_dir: Path, configured_remote: str) -> bool:
    """Return whether a public clone's origin/pushurl matches *configured_remote*."""

    try:
        origin = _bare_remote_url(clone_dir)
        pushurl = _bare_push_url(clone_dir)
    except Exception:
        return False
    if pushurl and _same_git_remote(pushurl, configured_remote):
        return True
    if origin and _same_git_remote(origin, configured_remote):
        return True
    fetch_url = _anonymous_fetch_url(configured_remote)
    if fetch_url and origin and _same_git_remote(origin, fetch_url):
        return True
    return False


def _bare_push_url(clone_dir: Path) -> str | None:
    result = run_sdd_git(
        ["config", "--get", "remote.origin.pushurl"],
        cwd=clone_dir,
        op="sdd.attachments.pushurl_probe",
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _run_bare_git(clone_dir: Path, args: list[str]) -> None:
    run_sdd_git(
        args,
        cwd=clone_dir,
        op="sdd.attachments.origin",
        check=False,
        capture_output=True,
        text=True,
    )


def _clone_bare_partial(
    clone_dir: Path, remote_url: str, *, role: str = ATTACHMENTS_PRIVATE_SIDECAR_ROLE
) -> None:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        result = run_sdd_git(
            [*_BARE_CLONE_ARGS, remote_url, str(clone_dir)],
            cwd=clone_dir.parent,
            op="sdd.attachments.clone",
            timeout=network_git_timeout(),
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
    except Exception as exc:
        raise SddMaterializationError(
            f"could not clone {role} sidecar {remote_url} into "
            f"{clone_dir}: {str(exc) or type(exc).__name__}"
        ) from exc
    if result.returncode != 0 or not is_bare_sidecar_clone(clone_dir):
        detail = (result.stderr or result.stdout or "").strip()
        raise SddMaterializationError(
            f"could not clone {role} sidecar {remote_url} into "
            f"{clone_dir}: {detail or f'git clone exited {result.returncode}'}"
        )


def _ensure_bare_head_commit(
    clone_dir: Path, *, role: str = ATTACHMENTS_PRIVATE_SIDECAR_ROLE
) -> None:
    head = run_sdd_git(
        ["rev-parse", "--verify", "HEAD"],
        cwd=clone_dir,
        op="sdd.attachments.head_probe",
        check=False,
        capture_output=True,
        text=True,
    )
    if head.returncode == 0:
        return
    branch_probe = run_sdd_git(
        ["symbolic-ref", "--short", "HEAD"],
        cwd=clone_dir,
        op="sdd.attachments.branch_probe",
        check=False,
        capture_output=True,
        text=True,
    )
    branch = branch_probe.stdout.strip() if branch_probe.returncode == 0 else ""
    if not branch:
        raise SddMaterializationError(
            f"{role} sidecar clone at {clone_dir} has an unborn "
            "HEAD with no branch to initialize"
        )
    tree = _empty_tree_hash(clone_dir)
    message = (
        ATTACHMENTS_PUBLIC_INIT_COMMIT_MESSAGE
        if role == ATTACHMENTS_SIDECAR_ROLE
        else ATTACHMENTS_INIT_COMMIT_MESSAGE
    )
    commit_probe = run_sdd_git(
        ["commit-tree", tree, "-m", message],
        cwd=clone_dir,
        op="sdd.attachments.init_commit",
        check=False,
        capture_output=True,
        text=True,
    )
    if commit_probe.returncode != 0:
        detail = (commit_probe.stderr or commit_probe.stdout or "").strip()
        raise SddMaterializationError(
            f"could not initialize {role} sidecar at {clone_dir}: "
            f"{detail or f'git commit-tree exited {commit_probe.returncode}'}"
        )
    commit = commit_probe.stdout.strip()
    if not commit:
        raise SddMaterializationError(
            f"could not initialize {role} sidecar at {clone_dir}: "
            "git commit-tree produced no commit hash"
        )
    update_probe = run_sdd_git(
        ["update-ref", f"refs/heads/{branch}", commit],
        cwd=clone_dir,
        op="sdd.attachments.init_branch",
        check=False,
        capture_output=True,
        text=True,
    )
    if update_probe.returncode != 0:
        detail = (update_probe.stderr or update_probe.stdout or "").strip()
        raise SddMaterializationError(
            f"could not initialize {role} sidecar at {clone_dir}: "
            f"{detail or f'git update-ref exited {update_probe.returncode}'}"
        )
    from sase.sdd._sidecar_git import push_sidecar

    try:
        push_sidecar(clone_dir)
    except Exception as exc:
        raise SddMaterializationError(
            f"could not push initialized {role} sidecar at {clone_dir}: {exc}"
        ) from exc


def _empty_tree_hash(clone_dir: Path) -> str:
    try:
        result = subprocess.run(
            sdd_git_command(["mktree"]),
            cwd=clone_dir,
            input="",
            capture_output=True,
            text=True,
            timeout=_LOCAL_PLUMBING_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SddMaterializationError(
            f"could not initialize attachments sidecar at {clone_dir}: "
            f"{str(exc) or type(exc).__name__}"
        ) from exc
    tree = (result.stdout or "").strip()
    if result.returncode != 0 or not tree:
        detail = (result.stderr or result.stdout or "").strip()
        raise SddMaterializationError(
            f"could not initialize attachments sidecar at {clone_dir}: "
            f"{detail or f'git mktree exited {result.returncode}'}"
        )
    return tree


def _bare_remote_url(clone_dir: Path) -> str | None:
    return _git_remote_url(clone_dir)


__all__ = [
    "ATTACHMENTS_INIT_COMMIT_MESSAGE",
    "ATTACHMENTS_PUBLIC_INIT_COMMIT_MESSAGE",
    "ensure_attachments_bare_clone",
    "ensure_attachments_private_bare_clone",
    "is_bare_sidecar_clone",
]
