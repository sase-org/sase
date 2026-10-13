"""Unrecorded local-commit detection and absorption for commit finalization.

An agent can run raw ``git commit`` in a linked or external checkout outside
the host stitch path. The worktree is then clean at turn end, so dirty-state
discovery sees nothing while the commits exist only locally. This module
closes that gap:

- :func:`unrecorded_local_commits` lists, per in-scope repository, the commits
  newer than the run-start ``finalizer_baseline.json`` ``head`` that no remote
  reaches and that the host's own stitch never recorded in
  ``commit_results.json``.
- :func:`absorb_raw_local_commits` implements the ``raw_commit_policy =
  absorb`` branch: eligible chains are soft-reset back to staged dirt so the
  ordinary obligation, declaration, and ``sase stitch create`` path commits
  and pushes them with SASE trailers.

Commits carrying a ``SASE_AGENT=`` trailer that names a different agent are a
concurrent agent's work, not this turn's raw commits: the discarded-work
guard already exempts foreign-agent races in shared clones, and the detector
agrees with it. Unattributed commits (no trailer) always count, and commits
trailered with this agent's own name count too, so the backstop still fails
closed for anything that could be this turn's work.

Only ``main``, ``sibling``, and opened ``external`` repos are in scope. SDD
stores and the agents prompt archive (both ``kind == "sdd"``) have their own
commit flows and are never treated as raw. Repos whose baseline record has no
``head`` (legacy artifacts, unborn HEAD, unreadable repo) are skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import re
import subprocess

from .commit_finalizer_baseline import load_finalizer_baseline_records
from .commit_finalizer_git_paths import normalize_path
from .commit_finalizer_git_status import (
    git_changed_files,
    split_pre_existing_changed_files,
)

_logger = logging.getLogger(__name__)

_GIT_TIMEOUT_SECONDS = 5

#: Repo kinds whose raw local commits are in scope. SDD stores and the agents
#: prompt archive (``sdd``) have their own commit flows.
_RAW_COMMIT_REPO_KINDS = frozenset({"main", "sibling", "external"})

#: Recovery ref pinning one absorbed HEAD per run, under ``refs/sase/``.
_RAW_COMMIT_RECOVERY_REF_PREFIX = "refs/sase/recovery/raw-commits/"


@dataclass(frozen=True)
class _RawCommit:
    """One local-only commit the host stitch path never recorded."""

    sha: str
    subject: str


@dataclass(frozen=True)
class RawCommitRepo:
    """One in-scope repo with unrecorded local commits."""

    kind: str
    name: str
    path: str
    baseline_head: str
    commits: tuple[_RawCommit, ...]


@dataclass(frozen=True)
class AbsorbedRawCommits:
    """One repo whose raw chain was soft-reset back to staged dirt."""

    kind: str
    name: str
    path: str
    commits: tuple[_RawCommit, ...]
    recovery_ref: str
    reset_target: str


def unrecorded_local_commits(
    artifact_root: Path | None,
) -> tuple[RawCommitRepo, ...]:
    """Return unrecorded local-only commits for every in-scope repo.

    Never raises: a missing or malformed baseline, an unreadable
    ``commit_results.json``, or any git failure yields fewer (or no) findings
    instead of an error, so detection degrades to pre-existing behavior.
    """

    if artifact_root is None:
        return ()
    try:
        records = load_finalizer_baseline_records(Path(artifact_root))
    except Exception:
        _logger.warning(
            "Failed to load finalizer baseline for raw-commit detection",
            exc_info=True,
        )
        return ()
    if not records:
        return ()
    try:
        recorded = _recorded_commit_shas(Path(artifact_root))
    except Exception:
        _logger.warning(
            "Failed to load commit results for raw-commit detection",
            exc_info=True,
        )
        recorded = {}
    findings: list[RawCommitRepo] = []
    for record in records:
        if record.kind not in _RAW_COMMIT_REPO_KINDS or not record.head:
            continue
        commits = _unrecorded_commits_for_repo(
            record.path,
            record.head,
            recorded.get(normalize_path(record.path), frozenset()),
        )
        if commits:
            findings.append(
                RawCommitRepo(
                    kind=record.kind,
                    name=record.name,
                    path=record.path,
                    baseline_head=record.head,
                    commits=commits,
                )
            )
    return tuple(sorted(findings, key=lambda finding: finding.path))


def absorb_raw_local_commits(
    project_dir: str,
    artifact_root: Path | None,
) -> tuple[AbsorbedRawCommits, ...]:
    """Soft-reset eligible raw chains back to staged dirt (idempotent).

    A repo qualifies only when its unrecorded commits form a linear chain
    with no merges, HEAD is attached to a branch, no rebase/merge/
    cherry-pick/am/revert/bisect is in progress, and none of the commits'
    paths overlaps a baseline-protected dirty path. Ineligible repos are left
    untouched for the execution-time backstop. After this runs, HEAD equals
    the reset target, so a second call finds nothing.

    Never raises: every per-repo failure is logged and left for the backstop.
    """

    _ = project_dir
    if artifact_root is None:
        return ()
    run_id = (os.environ.get("SASE_AGENT_TIMESTAMP") or "").strip()
    if not run_id:
        return ()
    root = Path(artifact_root)
    absorbed: list[AbsorbedRawCommits] = []
    try:
        findings = unrecorded_local_commits(root)
    except Exception:
        _logger.warning("Raw-commit absorption scan failed", exc_info=True)
        return ()
    for finding in findings:
        try:
            result = _absorb_one_repo(root, finding, run_id)
        except Exception:
            _logger.warning(
                "Failed to absorb raw commits in %s", finding.path, exc_info=True
            )
            continue
        if result is not None:
            absorbed.append(result)
    return tuple(absorbed)


def _run_git_mutating(
    repo_path: str, args: list[str]
) -> subprocess.CompletedProcess[str] | None:
    """Run one mutating git command with a bounded timeout, never raising.

    Plain subprocess (like the sidecar recovery-ref pinning) rather than the
    lock-retry runner: absorption touches only agent-owned main/sibling/
    external checkouts, never the contended shared stores.
    """

    try:
        return subprocess.run(
            ["git", "-C", repo_path, *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except Exception:
        return None


def _recorded_commit_shas(
    root: Path,
) -> dict[str, frozenset[str]]:
    """Map each normalized repo path to the host-recorded stitch shas."""

    try:
        payload = json.loads((root / "commit_results.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, list):
        return {}
    recorded: dict[str, set[str]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        cwd = item.get("cwd")
        sha = item.get("commit_sha")
        if not (isinstance(cwd, str) and isinstance(sha, str) and sha.strip()):
            continue
        recorded.setdefault(normalize_path(cwd), set()).add(sha.strip())
    return {path: frozenset(shas) for path, shas in recorded.items()}


def _unrecorded_commits_for_repo(
    repo_path: str,
    baseline_head: str,
    recorded_shas: frozenset[str],
) -> tuple[_RawCommit, ...]:
    """List local-only commits newer than *baseline_head*, oldest first.

    Skips commits attributed to a foreign agent; only unattributed commits
    and commits trailered with this agent's own name can be this turn's raw
    work.
    """

    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                repo_path,
                "log",
                "--reverse",
                "-z",
                "--format=%H%x1f%s%x1f%B",
                "HEAD",
                "--not",
                "--remotes",
                baseline_head,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except Exception:
        return ()
    if result.returncode != 0:
        return ()
    current_agent = _current_agent_name()
    commits: list[_RawCommit] = []
    for record in result.stdout.split("\0"):
        if "\x1f" not in record:
            continue
        sha, _, rest = record.partition("\x1f")
        subject, _, body = rest.partition("\x1f")
        sha = sha.strip()
        if not sha or sha in recorded_shas:
            continue
        if _is_foreign_agent_commit(body, current_agent):
            continue
        commits.append(_RawCommit(sha=sha, subject=subject.strip()))
    return tuple(commits)


def _current_agent_name() -> str | None:
    """Resolve this agent's name without ever raising.

    ``None`` means the name is unavailable; :func:`_is_foreign_agent_commit`
    then treats any trailered commit as foreign and keeps only unattributed
    commits, which always count.
    """

    try:
        from sase.workflows.commit.runtime_tags import resolve_local_agent_name

        return resolve_local_agent_name()
    except Exception:
        return None


def _is_foreign_agent_commit(message: str, current_agent: str | None) -> bool:
    """Return whether *message* attributes its commit to another agent.

    A missing or empty ``AGENT`` trailer is unattributed, never foreign: raw
    ``git commit`` outside the host path carries no trailer, so unattributed
    commits always count. A trailer naming this agent counts too. Anything
    else names a concurrent agent whose race the discarded-work guard already
    exempts. Never raises: an unreadable trailer fails closed to "not
    foreign".
    """

    try:
        from sase.workflows.commit.runtime_tags import parse_trailing_commit_tags

        recorded = parse_trailing_commit_tags(message).get("AGENT")
    except Exception:
        return False
    if not recorded:
        return False
    if current_agent is None:
        return True
    return not _is_same_agent(recorded, current_agent)


def _is_same_agent(recorded: str, current: str) -> bool:
    """Return whether a commit trailer name identifies the current agent."""

    return (
        recorded == current
        or recorded.startswith((f"{current}.", f"{current}--"))
        or current.startswith((f"{recorded}.", f"{recorded}--"))
    )


def _absorb_one_repo(
    root: Path,
    finding: RawCommitRepo,
    run_id: str,
) -> AbsorbedRawCommits | None:
    if not _is_eligible(root, finding):
        return None
    recovery_ref = _pin_recovery_ref(finding.path, run_id)
    if recovery_ref is None:
        return None
    reset_target = _reset_target(finding)
    if reset_target is None:
        return None
    reset = _run_git_mutating(finding.path, ["reset", "--soft", reset_target])
    if reset is None or reset.returncode != 0:
        _logger.warning("Soft reset failed for raw commits in %s", finding.path)
        return None
    return AbsorbedRawCommits(
        kind=finding.kind,
        name=finding.name,
        path=finding.path,
        commits=finding.commits,
        recovery_ref=recovery_ref,
        reset_target=reset_target,
    )


def _is_eligible(root: Path, finding: RawCommitRepo) -> bool:
    if _head_branch(finding.path) is None:
        return False
    if _operation_in_progress(finding.path):
        return False
    if not _is_linear(finding.path, finding.baseline_head):
        return False
    raw_paths = _raw_commit_paths(finding.path, finding.baseline_head)
    if raw_paths is None:
        return False
    protected = _protected_paths(root, finding.path)
    if any(path in protected for path in raw_paths):
        return False
    return True


def _head_branch(repo_path: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "symbolic-ref", "--quiet", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _operation_in_progress(repo_path: str) -> bool:
    """Return whether a sequencer-style git operation holds *repo_path*."""

    try:
        git_dir_result = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except Exception:
        return True
    if git_dir_result.returncode != 0:
        return True
    git_dir = (git_dir_result.stdout.strip() or ".git").strip()
    git_path = Path(git_dir)
    if not git_path.is_absolute():
        git_path = Path(repo_path) / git_path
    for flag in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG"):
        try:
            if (git_path / flag).exists():
                return True
        except OSError:
            return True
    for state_dir in ("rebase-merge", "rebase-apply"):
        try:
            if (git_path / state_dir).is_dir():
                return True
        except OSError:
            return True
    return False


def _is_linear(repo_path: str, baseline_head: str) -> bool:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                repo_path,
                "rev-list",
                "--merges",
                "--count",
                f"{baseline_head}..HEAD",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except Exception:
        return False
    if result.returncode != 0:
        return False
    return result.stdout.strip() == "0"


def _raw_commit_paths(repo_path: str, baseline_head: str) -> frozenset[str] | None:
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "diff", "--name-only", baseline_head, "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return frozenset(
        line.strip() for line in result.stdout.splitlines() if line.strip()
    )


def _protected_paths(root: Path, repo_path: str) -> frozenset[str]:
    """Return the baseline-protected paths that are still dirty in *repo_path*."""

    try:
        records = load_finalizer_baseline_records(root)
    except Exception:
        return frozenset()
    if records is None:
        return frozenset()
    normalized = normalize_path(repo_path)
    fingerprints: dict[str, tuple[str, str | None]] | None = None
    for record in records:
        if record.path == normalized:
            fingerprints = dict(record.fingerprints)
            break
    _still, pre_existing = split_pre_existing_changed_files(
        repo_path, git_changed_files(repo_path), fingerprints
    )
    return frozenset(pre_existing)


def _pin_recovery_ref(repo_path: str, run_id: str) -> str | None:
    safe_run_id = re.sub(r"[^A-Za-z0-9._-]+", "-", run_id).strip(".-")
    if not safe_run_id:
        return None
    ref = f"{_RAW_COMMIT_RECOVERY_REF_PREFIX}{safe_run_id}"
    pinned = _run_git_mutating(repo_path, ["update-ref", ref, "HEAD"])
    if pinned is None or pinned.returncode != 0:
        _logger.warning("Could not pin raw-commit recovery ref in %s", repo_path)
        return None
    return ref


def _reset_target(finding: RawCommitRepo) -> str | None:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                finding.path,
                "rev-parse",
                "--verify",
                f"{finding.commits[0].sha}^",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


__all__ = [
    "AbsorbedRawCommits",
    "RawCommitRepo",
    "absorb_raw_local_commits",
    "unrecorded_local_commits",
]
