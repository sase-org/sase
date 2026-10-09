#!/usr/bin/env python3
"""sase-core pairing, the ``--sync`` gate, and the pre-swap build check.

Stdlib-only: this module never imports ``sase`` because the installer must
work when the installed ``sase`` is missing or broken. Anything shared with
``sase`` (pin containment, the clean fast-forward rule) is mirrored here as
plain ``git`` subprocesses, and parity is enforced by tests that *may* import
``sase``.

The pairing rule (``pair_core``) resolves the core checkout from
``$SASE_CORE_DIR`` (else ``<sase checkout>/../sase-core``), reads the pin
from the checkout's ``sase-core-revision.txt`` working tree, and decides:

1. core missing              -> plan row "clone sase-org/sase-core"
2. pin object missing         -> ``git fetch``; still missing -> fatal
3. pin not in HEAD, clean and strictly behind its upstream (which already
   contains the pin) -> plan row "fast-forward sase-core <a> -> <b>"
4. pin not in HEAD otherwise  -> fatal, with pull/switch/``SASE_CORE_DIR``
   remedies (``SASE_ALLOW_STALE_CORE=1`` downgrades this to a warning row)
5. pin in HEAD               -> ready; dirty is a warning row
   (consequential, allowed)

then the ``sase-core-rs`` version-window check runs
(``tools/validate_sase_core_rs_version``): behind the floor is fatal (or a
warning row under ``SASE_ALLOW_STALE_CORE=1``), ahead is a dim note.

Rule 3 mirrors ``sase._linked_repo_workspaces.refresh_clean_linked_checkout``:
clean, attached, has an upstream, strictly behind -> ``merge --ff-only``.
Only the plan row is produced here; the clone/fast-forward execute in the
installer's prepare stage (the engine-dev phase wires it).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import _sase_install_env as install_env


#: Pin file in the sase checkout naming the required sase-core commit.
PIN_FILENAME = "sase-core-revision.txt"

#: Clone source used when the core checkout is missing (overridable in tests).
DEFAULT_CORE_REMOTE = "https://github.com/sase-org/sase-core.git"

#: ``sase_core_py`` crate directory inside a sase-core checkout.
CORE_PY_CRATE = Path("crates") / "sase_core_py"

#: Shared cargo target dir, matching what ``rust-dev-install`` uses so a
#: pre-swap ``maturin build`` warms the post-swap ``maturin develop``.
UV_TOOL_TARGET_DIRNAME = "uv-tool-py"

#: Cargo profile the pre-swap build check and ``rust-dev-install`` share.
RUST_DEV_PROFILE = "dev-update"

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

_GIT_PROBE_TIMEOUT = 10.0
_GIT_FETCH_TIMEOUT = 120.0
_GIT_MERGE_TIMEOUT = 120.0
_VALIDATOR_TIMEOUT = 120.0
_BUILD_TIMEOUT = 600.0


class CorePairingError(Exception):
    """A dev pairing that cannot proceed (the entry point reports it)."""


def _short(sha: str, width: int = 9) -> str:
    return sha[:width]


def read_pin_text(checkout_root: str | Path) -> str | None:
    """Return the raw pin file contents, or None when unreadable/blank."""
    try:
        text = (Path(checkout_root) / PIN_FILENAME).read_text(encoding="utf-8")
    except OSError:
        return None
    return text.strip() or None


def read_pin(checkout_root: str | Path) -> str:
    """Return the required core sha, raising :class:`CorePairingError`."""
    raw = read_pin_text(checkout_root)
    if raw is None:
        raise CorePairingError(
            f"{PIN_FILENAME} is missing from {checkout_root}; cannot pair sase-core"
        )
    first = raw.split()[0] if raw.split() else ""
    if not _SHA_RE.fullmatch(first):
        raise CorePairingError(
            f"{PIN_FILENAME} in {checkout_root} does not hold a 40-hex "
            f"commit sha (saw {first!r}); cannot pair sase-core"
        )
    return first


def core_remote(env: Mapping[str, str] | None = None) -> str:
    """Return the sase-core clone URL (overridable for tests)."""
    source = os.environ if env is None else env
    raw = (source.get(install_env.CORE_REMOTE_ENV_VAR) or "").strip()
    return raw or DEFAULT_CORE_REMOTE


def stale_allowed(env: Mapping[str, str] | None = None) -> bool:
    """Return whether ``SASE_ALLOW_STALE_CORE=1`` downgrades stale failures."""
    source = os.environ if env is None else env
    return (source.get(install_env.STALE_CORE_ENV_VAR) or "") == "1"


def _path_bin(name: str, env: Mapping[str, str] | None) -> str | None:
    if env is not None and "PATH" in env:
        return shutil.which(name, path=env["PATH"])
    return shutil.which(name)


def _git_env(env: Mapping[str, str] | None) -> dict[str, str]:
    merged = dict(env) if env is not None else dict(os.environ)
    merged.setdefault("GIT_TERMINAL_PROMPT", "0")
    return merged


def _run_git(
    repo: str | Path,
    *args: str,
    env: Mapping[str, str] | None = None,
    timeout: float = _GIT_PROBE_TIMEOUT,
) -> subprocess.CompletedProcess[str] | None:
    """Run ``git -C repo args``; return None when git cannot run at all."""
    exe = _path_bin("git", env)
    if exe is None:
        return None
    try:
        return subprocess.run(
            [exe, "-C", str(repo), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_git_env(env),
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


@dataclass(frozen=True)
class CoreGit:
    """Probed git state for one core checkout (read-only, no mutation)."""

    exists: bool = False
    is_repo: bool = False
    has_cargo: bool = False
    head: str | None = None
    branch: str | None = None
    detached: bool = False
    dirty: bool = False
    upstream: str | None = None
    remote: str | None = None
    ahead: int | None = None
    behind: int | None = None

    @property
    def attached(self) -> bool:
        """Return whether HEAD is on a branch (not detached)."""
        return not self.detached and self.branch is not None

    @property
    def strictly_behind(self) -> bool:
        """Return whether HEAD is strictly behind its upstream."""
        return self.ahead == 0 and self.behind is not None and self.behind > 0

    @property
    def diverged(self) -> bool:
        """Return whether HEAD and its upstream diverged."""
        return bool(self.ahead and self.behind)


def _ahead_behind(
    repo: str | Path, upstream: str, *, env: Mapping[str, str] | None
) -> tuple[int | None, int | None]:
    result = _run_git(
        repo, "rev-list", "--left-right", "--count", f"HEAD...{upstream}", env=env
    )
    if result is None or result.returncode != 0:
        return None, None
    try:
        ahead_raw, behind_raw = result.stdout.split()
        return int(ahead_raw), int(behind_raw)
    except ValueError:
        return None, None


def classify_core_git(
    core_dir: str | Path, *, env: Mapping[str, str] | None = None
) -> CoreGit:
    """Probe the core checkout's git state without changing anything."""
    root = Path(core_dir)
    if not root.is_dir():
        return CoreGit()
    if not (root / "Cargo.toml").is_file():
        return CoreGit(exists=True)
    toplevel = _run_git(root, "rev-parse", "--show-toplevel", env=env)
    if toplevel is None or toplevel.returncode != 0:
        return CoreGit(exists=True, has_cargo=True)
    head = _run_git(root, "rev-parse", "HEAD", env=env)
    head_sha = (
        head.stdout.strip() if head is not None and head.returncode == 0 else None
    )
    branch_proc = _run_git(root, "symbolic-ref", "--quiet", "--short", "HEAD", env=env)
    if branch_proc is not None and branch_proc.returncode == 0:
        branch: str | None = branch_proc.stdout.strip() or None
        detached = False
    else:
        branch = None
        detached = True
    dirty_proc = _run_git(root, "status", "--porcelain", env=env)
    dirty = bool(
        dirty_proc is not None
        and dirty_proc.returncode == 0
        and dirty_proc.stdout.strip()
    )
    upstream_proc = _run_git(
        root,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
        env=env,
    )
    upstream: str | None = None
    remote: str | None = None
    ahead: int | None = None
    behind: int | None = None
    if upstream_proc is not None and upstream_proc.returncode == 0:
        upstream = upstream_proc.stdout.strip() or None
    if upstream is not None and branch is not None:
        remote_proc = _run_git(
            root, "config", "--get", f"branch.{branch}.remote", env=env
        )
        if remote_proc is not None and remote_proc.returncode == 0:
            remote = remote_proc.stdout.strip() or None
        ahead, behind = _ahead_behind(root, upstream, env=env)
    return CoreGit(
        exists=True,
        is_repo=True,
        has_cargo=True,
        head=head_sha,
        branch=branch,
        detached=detached,
        dirty=dirty,
        upstream=upstream,
        remote=remote,
        ahead=ahead,
        behind=behind,
    )


def object_exists(
    core_dir: str | Path, sha: str, *, env: Mapping[str, str] | None = None
) -> bool:
    """Return whether *sha* names a commit object in the core checkout."""
    result = _run_git(core_dir, "cat-file", "-e", f"{sha}^{{commit}}", env=env)
    return result is not None and result.returncode == 0


def contains_revision(
    core_dir: str | Path,
    sha: str,
    ref: str = "HEAD",
    *,
    env: Mapping[str, str] | None = None,
) -> bool | None:
    """Return whether *sha* is an ancestor of *ref* (None when undecidable).

    Mirrors ``sase.dev_update.core_pin.core_contains_revision``; parity is
    enforced by tests that import ``sase``.
    """
    if not _SHA_RE.fullmatch(sha):
        return None
    known = _run_git(core_dir, "cat-file", "-e", f"{sha}^{{commit}}", env=env)
    if known is None:
        return None
    if known.returncode != 0:
        error = known.stderr.lower()
        if known.returncode == 1 or any(
            marker in error
            for marker in (
                "not a valid object name",
                "could not get object info",
                "bad object",
            )
        ):
            return False
        return None
    ancestor = _run_git(core_dir, "merge-base", "--is-ancestor", sha, ref, env=env)
    if ancestor is None:
        return None
    if ancestor.returncode == 0:
        return True
    if ancestor.returncode == 1:
        return False
    return None


def commits_ahead(
    core_dir: str | Path,
    pin: str,
    ref: str = "HEAD",
    *,
    env: Mapping[str, str] | None = None,
) -> int | None:
    """Return ``rev-list --count pin..ref``, or None when git cannot answer."""
    result = _run_git(core_dir, "rev-list", "--count", f"{pin}..{ref}", env=env)
    if result is None or result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def fetch_remote(
    core_dir: str | Path,
    remote: str,
    *,
    env: Mapping[str, str] | None = None,
) -> str | None:
    """Fetch *remote*; return None on success, else a one-line error."""
    result = _run_git(
        core_dir,
        "fetch",
        "--quiet",
        "--tags",
        remote,
        env=env,
        timeout=_GIT_FETCH_TIMEOUT,
    )
    if result is None:
        return "git is not available"
    if result.returncode != 0:
        tail = (result.stderr.strip() or "unknown error").splitlines()
        return tail[-1].strip() if tail else "unknown error"
    return None


@dataclass(frozen=True)
class CorePairing:
    """The pairing decision for one dev install (feeds the dev plan rows)."""

    action: str
    kind: str
    consequential: bool
    note: str
    warnings: tuple[str, ...] = ()
    pin: str | None = None
    head: str | None = None
    branch: str | None = None
    upstream: str | None = None
    remote_url: str | None = None
    commits_past_pin: int | None = None


def _validator_argv(checkout_root: str | Path, core_dir: str | Path) -> list[str]:
    script = Path(__file__).resolve().parent / "validate_sase_core_rs_version"
    return [
        sys.executable,
        str(script),
        "--sase-core-dir",
        str(core_dir),
        "--pyproject",
        str(Path(checkout_root) / "pyproject.toml"),
    ]


def check_version_window(
    checkout_root: str | Path,
    core_dir: str | Path,
    *,
    env: Mapping[str, str] | None = None,
) -> tuple[str | None, str | None, tuple[str, ...]]:
    """Run the ``sase-core-rs`` floor/ceiling check.

    Return ``(fatal, note_suffix, warnings)``: *fatal* is the ``✗`` text when
    the pairing cannot proceed, *note_suffix* extends the core plan-row note.
    """
    try:
        completed = subprocess.run(
            _validator_argv(checkout_root, core_dir),
            check=False,
            capture_output=True,
            text=True,
            timeout=_VALIDATOR_TIMEOUT,
            env=_git_env(env),
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"could not check the sase-core-rs version window: {exc}", None, ()
    if completed.returncode == 0:
        return None, None, ()
    tail_lines = (completed.stderr.strip() or completed.stdout.strip()).splitlines()
    tail = tail_lines[-1].strip() if tail_lines else "unknown error"
    if completed.returncode == 4:
        return (
            None,
            "core ahead of the published sase-core-rs window (ignored for dev builds)",
            (),
        )
    if completed.returncode == 3:
        if stale_allowed(env):
            return (
                None,
                "behind the sase-core-rs floor "
                "(proceeding because SASE_ALLOW_STALE_CORE=1)",
                (),
            )
        return (
            f"sase-core checkout is behind the sase-core-rs floor: {tail} "
            "Set SASE_ALLOW_STALE_CORE=1 to proceed anyway "
            "(intentional bisects only).",
            None,
            (),
        )
    return f"could not check the sase-core-rs version window: {tail}", None, ()


def _rule4_fatal(pin: str, git: CoreGit, core_dir: str | Path, head_desc: str) -> str:
    """Build the rule-4 fatal text with the exact state and remedies."""
    pin_short = _short(pin)
    if git.dirty:
        state = "the core checkout is dirty"
    elif git.detached:
        state = f"the core checkout is detached at {head_desc}"
    elif git.upstream is None:
        state = "the core checkout has no upstream"
    elif git.diverged:
        state = (
            f"the core checkout diverged from {git.upstream} "
            f"(+{git.ahead} -{git.behind})"
        )
    elif (git.ahead or 0) > 0:
        state = (
            f"the core checkout is {git.ahead} ahead of {git.upstream} "
            f"without containing pin {pin_short}"
        )
    else:
        state = f"even {git.upstream} lacks pin {pin_short}; fetch the core checkout"
    return (
        f"sase-core {head_desc} does not contain pin {pin_short}: {state}. "
        f"Pull or switch the core checkout ({core_dir}), or point "
        "SASE_CORE_DIR at a checkout that contains the pin."
    )


def pair_core(
    checkout_root: str | Path,
    core_dir: str | Path,
    *,
    env: Mapping[str, str] | None = None,
) -> CorePairing:
    """Apply the pairing rule; raise :class:`CorePairingError` when stuck.

    Rules 1 (clone) and 3 (fast-forward) return plan rows for the installer's
    prepare stage to execute. Rule 2 fetches immediately: a dry run otherwise
    cannot tell a stale clone from a wrong pin.
    """
    pin = read_pin(checkout_root)
    pin_short = _short(pin)
    checkout = Path(checkout_root)
    core = Path(core_dir)

    if not core.is_dir():
        remote = core_remote(env)
        display = "sase-org/sase-core" if remote == DEFAULT_CORE_REMOTE else remote
        return CorePairing(
            action="clone",
            kind="add",
            consequential=False,
            note=f"clone {display} -> {core}",
            pin=pin,
            remote_url=remote,
        )

    git = classify_core_git(core, env=env)
    if not git.is_repo:
        raise CorePairingError(
            f"{core} is not a git checkout; remove it or point "
            "SASE_CORE_DIR at the sase-core checkout to pair"
        )
    if not git.has_cargo:
        raise CorePairingError(
            f"{core} has no Cargo.toml; it is not a sase-core checkout. "
            "Remove it or point SASE_CORE_DIR at the sase-core checkout to pair."
        )
    head_desc = _short(git.head) if git.head else "HEAD"
    if git.head is None:
        raise CorePairingError(
            f"could not read HEAD of the core checkout at {core}; is git working?"
        )

    if not object_exists(core, pin, env=env):
        remote = git.remote or "origin"
        failure = fetch_remote(core, remote, env=env)
        if failure is not None:
            if stale_allowed(env):
                return CorePairing(
                    action="stale",
                    kind="keep",
                    consequential=True,
                    note=(
                        f"could not fetch {remote} for {core} ({failure}); "
                        "proceeding because SASE_ALLOW_STALE_CORE=1"
                    ),
                    pin=pin,
                    head=git.head,
                    branch=git.branch,
                    upstream=git.upstream,
                )
            raise CorePairingError(
                f"could not fetch {remote} for {core}: {failure}; "
                f"pin {pin_short} is not in the checkout"
            )
        git = classify_core_git(core, env=env)
        if not object_exists(core, pin, env=env):
            if stale_allowed(env):
                return CorePairing(
                    action="stale",
                    kind="keep",
                    consequential=True,
                    note=(
                        f"pin {pin_short} is not on the core's remote; "
                        "proceeding because SASE_ALLOW_STALE_CORE=1"
                    ),
                    pin=pin,
                    head=git.head,
                    branch=git.branch,
                    upstream=git.upstream,
                )
            raise CorePairingError(
                f"pin {pin_short} is not on the core's remote ({remote}); "
                "fetch the core checkout or fix sase-core-revision.txt"
            )

    contained = contains_revision(core, pin, "HEAD", env=env)
    if contained is None:
        raise CorePairingError(
            f"could not compare pin {pin_short} against the core checkout "
            f"at {core}; is git working?"
        )

    if contained:
        ahead = commits_ahead(core, pin, "HEAD", env=env)
        past = f" +{ahead}" if ahead else ""
        where = git.branch or "detached"
        note = (
            f"{where} @ {_short(git.head or '')} "
            f"contains pin {pin_short} ({PIN_FILENAME}){past}"
        )
        consequential = False
        if git.dirty:
            note += " - dirty worktree"
            consequential = True
        fatal, suffix, warnings = check_version_window(checkout, core, env=env)
        if fatal is not None:
            raise CorePairingError(fatal)
        if suffix is not None:
            if "SASE_ALLOW_STALE_CORE=1" in suffix:
                consequential = True
            note += f" - {suffix}"
        return CorePairing(
            action="ready",
            kind="keep",
            consequential=consequential,
            note=note,
            warnings=warnings,
            pin=pin,
            head=git.head,
            branch=git.branch,
            upstream=git.upstream,
            commits_past_pin=ahead,
        )

    if stale_allowed(env):
        where = git.branch or "detached"
        return CorePairing(
            action="stale",
            kind="keep",
            consequential=True,
            note=(
                f"pin {pin_short} not in {where} @ {_short(git.head or '')}; "
                "proceeding because SASE_ALLOW_STALE_CORE=1"
            ),
            pin=pin,
            head=git.head,
            branch=git.branch,
            upstream=git.upstream,
        )

    if (
        not git.dirty
        and git.attached
        and git.upstream is not None
        and git.strictly_behind
        and git.head is not None
    ):
        upstream_head = _run_git(core, "rev-parse", "--short=9", git.upstream, env=env)
        upstream_short = (
            upstream_head.stdout.strip()
            if upstream_head is not None and upstream_head.returncode == 0
            else git.upstream
        )
        upstream_contains = contains_revision(core, pin, git.upstream, env=env)
        if upstream_contains:
            return CorePairing(
                action="fast-forward",
                kind="upgrade",
                consequential=False,
                note=(f"fast-forward sase-core {_short(git.head)} -> {upstream_short}"),
                pin=pin,
                head=git.head,
                branch=git.branch,
                upstream=git.upstream,
            )

    raise CorePairingError(_rule4_fatal(pin, git, core, head_desc))


@dataclass
class SyncRepo:
    """One ``--sync`` checkout: fetch always, merge only for real runs."""

    path: str
    ok: bool
    detail: str
    skipped: bool = False
    before: str | None = None
    after: str | None = None
    shortstat: str | None = None


def _shortstat(
    repo: str | Path, old: str, new: str, *, env: Mapping[str, str] | None
) -> str | None:
    result = _run_git(repo, "diff", "--shortstat", f"{old}..{new}", env=env)
    if result is None or result.returncode != 0:
        return None
    text = result.stdout.strip()
    return text or None


def sync_repo(
    path: str | Path, *, merge: bool, env: Mapping[str, str] | None = None
) -> SyncRepo:
    """Fetch one checkout (and fast-forward it when *merge* is true)."""
    repo = str(path)
    toplevel = _run_git(repo, "rev-parse", "--show-toplevel", env=env)
    if toplevel is None or toplevel.returncode != 0:
        return SyncRepo(
            path=repo, ok=True, skipped=True, detail="not a git checkout; skipping"
        )
    root = toplevel.stdout.strip()
    dirty_proc = _run_git(root, "status", "--porcelain", env=env)
    dirty = dirty_proc is not None and dirty_proc.returncode == 0
    dirty_text = dirty_proc.stdout if dirty_proc is not None else ""
    if dirty and dirty_text.strip():
        count = len(dirty_text.strip().splitlines())
        noun = "path" if count == 1 else "paths"
        return SyncRepo(path=root, ok=False, detail=f"dirty worktree ({count} {noun})")
    branch_proc = _run_git(root, "symbolic-ref", "--quiet", "--short", "HEAD", env=env)
    if branch_proc is None or branch_proc.returncode != 0:
        head_proc = _run_git(root, "rev-parse", "--short=9", "HEAD", env=env)
        head = head_proc.stdout.strip() if head_proc is not None else "HEAD"
        return SyncRepo(path=root, ok=False, detail=f"detached HEAD at {head}")
    upstream_proc = _run_git(
        root,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
        env=env,
    )
    upstream = (
        upstream_proc.stdout.strip()
        if upstream_proc is not None and upstream_proc.returncode == 0
        else None
    )
    if upstream is None:
        return SyncRepo(path=root, ok=False, detail="has no upstream; cannot --sync")
    branch = branch_proc.stdout.strip()
    remote_proc = _run_git(root, "config", "--get", f"branch.{branch}.remote", env=env)
    remote = (
        remote_proc.stdout.strip()
        if remote_proc is not None and remote_proc.returncode == 0
        else "origin"
    )
    before_proc = _run_git(root, "rev-parse", "--short=9", "HEAD", env=env)
    before = before_proc.stdout.strip() if before_proc is not None else "HEAD"
    failure = fetch_remote(root, remote or "origin", env=env)
    if failure is not None:
        return SyncRepo(
            path=root,
            ok=False,
            before=before,
            detail=f"fetch {remote} failed: {failure}",
        )
    ahead, behind = _ahead_behind(root, upstream, env=env)
    if ahead is None or behind is None:
        return SyncRepo(
            path=root,
            ok=False,
            before=before,
            detail=f"could not compare HEAD against {upstream}",
        )
    if ahead > 0 and behind > 0:
        return SyncRepo(
            path=root,
            ok=False,
            before=before,
            detail=f"diverged from {upstream} (+{ahead} -{behind})",
        )
    up_proc = _run_git(root, "rev-parse", "--short=9", upstream, env=env)
    upstream_short = up_proc.stdout.strip() if up_proc is not None else upstream
    if behind == 0:
        return SyncRepo(
            path=root,
            ok=True,
            before=before,
            after=before,
            detail=f"already up to date with {upstream} ({before})",
        )
    if not merge:
        return SyncRepo(
            path=root,
            ok=True,
            before=before,
            after=upstream_short,
            detail=f"would fast-forward {before} -> {upstream_short} (+{behind})",
            shortstat=_shortstat(root, "HEAD", upstream, env=env),
        )
    merged = _run_git(
        root, "merge", "--ff-only", upstream, env=env, timeout=_GIT_MERGE_TIMEOUT
    )
    if merged is None or merged.returncode != 0:
        tail = ""
        if merged is not None:
            lines = (merged.stderr.strip() or "unknown error").splitlines()
            tail = f": {lines[-1].strip()}" if lines else ""
        return SyncRepo(
            path=root,
            ok=False,
            before=before,
            detail=f"could not fast-forward to {upstream}{tail}",
        )
    after_proc = _run_git(root, "rev-parse", "--short=9", "HEAD", env=env)
    after = after_proc.stdout.strip() if after_proc is not None else upstream_short
    return SyncRepo(
        path=root,
        ok=True,
        before=before,
        after=after,
        detail=f"fast-forwarded {before} -> {after}",
        shortstat=_shortstat(root, before, after, env=env),
    )


def sync_repos(
    paths: Sequence[str | Path],
    *,
    merge: bool,
    env: Mapping[str, str] | None = None,
) -> list[SyncRepo]:
    """Fetch every checkout (and fast-forward each when *merge* is true)."""
    seen: set[str] = set()
    results: list[SyncRepo] = []
    for path in paths:
        key = os.path.abspath(os.path.expanduser(os.fspath(path)))
        if key in seen:
            continue
        seen.add(key)
        results.append(sync_repo(path, merge=merge, env=env))
    return results


@dataclass(frozen=True)
class BuildCheck:
    """Outcome of compiling sase-core before the swap (old install untouched)."""

    ok: bool
    method: str
    detail: str
    elapsed: float


def _cargo_env(
    target_dir: str | Path,
    tool_venv: str | Path | None,
    env: Mapping[str, str] | None,
) -> dict[str, str]:
    merged = _git_env(env)
    merged["CARGO_TARGET_DIR"] = str(target_dir)
    merged["CARGO_BUILD_BUILD_DIR"] = str(Path(target_dir) / "build")
    merged["CARGO_INCREMENTAL"] = "0"
    merged.setdefault("CARGO_NET_RETRY", "10")
    merged.setdefault("CARGO_HTTP_MULTIPLEXING", "false")
    merged["PYO3_USE_ABI3_FORWARD_COMPATIBILITY"] = "1"
    if tool_venv is not None:
        merged["VIRTUAL_ENV"] = str(tool_venv)
    return merged


def pre_swap_build_check(
    core_dir: str | Path,
    *,
    tool_python: str | Path,
    env: Mapping[str, str] | None = None,
    timeout: float = _BUILD_TIMEOUT,
) -> BuildCheck:
    """Compile sase-core into a temp dir so a broken tree fails pre-swap.

    Preferred: ``maturin build --profile dev-update`` (via ``uv run`` so only
    uv is required) with the same target dir, environment, and interpreter
    ``rust-dev-install`` uses, letting the post-swap ``maturin develop``
    reuse the artifacts. The interpreter is pinned to ``tool_python`` (with
    ``VIRTUAL_ENV`` pointed at the tool venv) when the tool env exists; on
    a fresh install with no tool env yet, the unpinned command runs.
    Fallback: ``cargo check`` of the same package when uv is unavailable.
    """
    started = time.monotonic()
    crate = Path(core_dir) / CORE_PY_CRATE
    if not crate.is_dir():
        return BuildCheck(
            ok=False,
            method="none",
            detail=f"no sase_core_py crate at {crate}",
            elapsed=time.monotonic() - started,
        )
    target = Path(core_dir) / "target" / UV_TOOL_TARGET_DIRNAME
    venv = Path(tool_python).parent.parent
    build_env = _cargo_env(target, venv, env)
    path = build_env.get("PATH", os.environ.get("PATH", ""))
    uv = shutil.which("uv", path=path)
    if uv is not None:
        outdir = tempfile.mkdtemp(prefix="sase-core-build-check-")
        # `uv run` swaps VIRTUAL_ENV for an ephemeral env, so without a
        # pinned interpreter maturin builds against the wrong Python and
        # the post-swap `maturin develop` recompiles pyo3. Pin the tool
        # interpreter (and its venv) when the tool env already exists.
        build_argv: list[str] = [
            uv,
            "run",
            "--no-project",
            "--with",
            "maturin",
            "maturin",
            "build",
            "--profile",
            RUST_DEV_PROFILE,
            "--out",
            outdir,
        ]
        if Path(tool_python).is_file():
            env_bin = shutil.which("env", path=path) or "/usr/bin/env"
            build_argv = [
                uv,
                "run",
                "--no-project",
                "--with",
                "maturin",
                "--",
                env_bin,
                f"VIRTUAL_ENV={venv}",
                "maturin",
                "build",
                "--profile",
                RUST_DEV_PROFILE,
                "--interpreter",
                str(tool_python),
                "--out",
                outdir,
            ]
        try:
            completed = subprocess.run(
                build_argv,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=build_env,
                cwd=str(crate),
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return BuildCheck(
                ok=False,
                method="maturin-build",
                detail=f"could not run the maturin build: {exc}",
                elapsed=time.monotonic() - started,
            )
        finally:
            shutil.rmtree(outdir, ignore_errors=True)
        elapsed = time.monotonic() - started
        if completed.returncode == 0:
            return BuildCheck(
                ok=True,
                method="maturin-build",
                detail=f"maturin build ok ({elapsed:.1f}s)",
                elapsed=elapsed,
            )
        tail_lines = (completed.stderr.strip() or "unknown error").splitlines()
        return BuildCheck(
            ok=False,
            method="maturin-build",
            detail=f"maturin build failed: {tail_lines[-1].strip()}",
            elapsed=elapsed,
        )
    cargo = shutil.which("cargo", path=path)
    if cargo is None:
        return BuildCheck(
            ok=False,
            method="none",
            detail="need uv or cargo on PATH for the pre-swap build check",
            elapsed=time.monotonic() - started,
        )
    try:
        completed = subprocess.run(
            [cargo, "check", "--profile", RUST_DEV_PROFILE],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=build_env,
            cwd=str(crate),
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return BuildCheck(
            ok=False,
            method="cargo-check",
            detail=f"could not run cargo check: {exc}",
            elapsed=time.monotonic() - started,
        )
    elapsed = time.monotonic() - started
    if completed.returncode == 0:
        return BuildCheck(
            ok=True,
            method="cargo-check",
            detail=f"cargo check ok ({elapsed:.1f}s)",
            elapsed=elapsed,
        )
    tail_lines = (completed.stderr.strip() or "unknown error").splitlines()
    return BuildCheck(
        ok=False,
        method="cargo-check",
        detail=f"cargo check failed: {tail_lines[-1].strip()}",
        elapsed=elapsed,
    )


__all__ = [
    "CORE_PY_CRATE",
    "DEFAULT_CORE_REMOTE",
    "PIN_FILENAME",
    "RUST_DEV_PROFILE",
    "UV_TOOL_TARGET_DIRNAME",
    "BuildCheck",
    "CoreGit",
    "CorePairing",
    "CorePairingError",
    "SyncRepo",
    "check_version_window",
    "classify_core_git",
    "commits_ahead",
    "contains_revision",
    "core_remote",
    "fetch_remote",
    "object_exists",
    "pair_core",
    "pre_swap_build_check",
    "read_pin",
    "read_pin_text",
    "stale_allowed",
    "sync_repo",
    "sync_repos",
]
