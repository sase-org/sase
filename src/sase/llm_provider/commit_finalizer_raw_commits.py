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
agrees with it. An agent's own trailer in global form
(``owner.machine.<name>``) or linked form (``[owner.machine.<name>][n]``)
counts as own. A footer with a SASE ``TYPE`` tag and no ``AGENT`` tag is
SASE tooling run outside any agent, so it is skipped. Commits with neither
tag still count, since that is what raw ``git commit`` produces.

Only ``main``, ``sibling``, opened ``linked``, and opened ``external`` repos
are in scope. SDD stores and the agents prompt archive (both
``kind == "sdd"``) have their own commit flows and are never treated as raw.
Repos whose baseline record has no ``head`` (legacy artifacts, unborn HEAD,
unreadable repo) are skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import re
import subprocess

from .commit_finalizer_agent_provenance import agent_provenance_matches
from .commit_finalizer_baseline import load_finalizer_baseline_records
from .commit_finalizer_git_paths import normalize_path

_logger = logging.getLogger(__name__)

_GIT_TIMEOUT_SECONDS = 5

#: Repo kinds whose raw local commits are in scope. SDD stores and the agents
#: prompt archive (``sdd``) have their own commit flows. ``OpenedRepoKind``
#: values (``linked``, ``external``) must stay in this set; a unit test
#: guards that drift.
_RAW_COMMIT_REPO_KINDS = frozenset({"main", "sibling", "linked", "external"})

#: Recovery ref pinning one absorbed HEAD per run, under ``refs/sase/``.
_RAW_COMMIT_RECOVERY_REF_PREFIX = "refs/sase/recovery/raw-commits/"


@dataclass(frozen=True)
class _RawCommit:
    """One local-only commit the host stitch path never recorded."""

    sha: str
    subject: str


@dataclass(frozen=True)
class _AbsorptionProof:
    """Git evidence proving one complete, owned suffix can be reset."""

    observed_head: str
    reset_target: str
    touched_paths: frozenset[str]


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
    linked/external checkouts, never the contended shared stores.
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

    Skips commits attributed to a foreign agent and SASE tool commits that
    carry a ``TYPE`` tag with no ``AGENT`` tag. Only unattributed raw
    commits and commits trailered with this agent's own name can be this
    turn's raw work.
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
    then treats any ``AGENT``-trailered commit as foreign. Unattributed
    commits still count unless they carry a SASE ``TYPE`` tag.
    """

    try:
        from sase.workflows.commit.runtime_tags import resolve_local_agent_name

        return resolve_local_agent_name()
    except Exception:
        return None


def _is_foreign_agent_commit(message: str, current_agent: str | None) -> bool:
    """Return whether *message* is not this turn's raw commit.

    A missing or empty ``AGENT`` trailer is unattributed. Raw ``git commit``
    outside the host path carries no trailer, so unattributed commits with
    no SASE ``TYPE`` tag always count. A footer with a ``TYPE`` tag and no
    ``AGENT`` tag is SASE tooling run outside any agent and is skipped. A
    trailer naming this agent, including global
    (``owner.machine.<name>``) and linked (``[owner.machine.<name>][n]``)
    forms, counts as own. Anything else names a concurrent agent whose race
    the discarded-work guard already exempts. Never raises: an unreadable
    trailer fails closed to "not foreign".
    """

    try:
        from sase.workflows.commit.runtime_tags import parse_trailing_commit_tags

        tags = parse_trailing_commit_tags(message)
    except Exception:
        return False
    recorded = tags.get("AGENT")
    if not recorded:
        return bool(tags.get("TYPE"))
    if current_agent is None:
        return True
    return not agent_provenance_matches(recorded, current_agent)


def _absorb_one_repo(
    root: Path,
    finding: RawCommitRepo,
    run_id: str,
) -> AbsorbedRawCommits | None:
    if _head_branch(finding.path) is None:
        return None
    if _operation_in_progress(finding.path):
        return None
    proof = _prove_owned_suffix(finding)
    if proof is None:
        return None
    protected = _protected_paths(root, finding.path)
    if protected is None or proof.touched_paths & protected:
        return None

    # The proof describes one observed tip. Re-read it immediately before the
    # recovery pin and again before resetting so a concurrent commit cannot
    # expand the range whose ownership was just proved.
    if _head_commit_id(finding.path) != proof.observed_head:
        return None
    recovery_ref = _pin_recovery_ref(finding.path, run_id, proof.observed_head)
    if recovery_ref is None:
        return None
    if _head_commit_id(finding.path) != proof.observed_head:
        _logger.warning(
            "Raw-commit tip changed after recovery pin in %s; leaving it untouched",
            finding.path,
        )
        return None
    reset = _run_git_mutating(finding.path, ["reset", "--soft", proof.reset_target])
    if reset is None or reset.returncode != 0:
        _logger.warning("Soft reset failed for raw commits in %s", finding.path)
        return None
    return AbsorbedRawCommits(
        kind=finding.kind,
        name=finding.name,
        path=finding.path,
        commits=finding.commits,
        recovery_ref=recovery_ref,
        reset_target=proof.reset_target,
    )


def _prove_owned_suffix(finding: RawCommitRepo) -> _AbsorptionProof | None:
    """Prove findings are the complete linear suffix from their parent to HEAD."""

    observed_head = _head_commit_id(finding.path)
    if observed_head is None or not finding.commits:
        return None
    commit_shas = tuple(commit.sha for commit in finding.commits)
    if commit_shas[-1] != observed_head:
        return None
    reset_target = _commit_parent(finding.path, commit_shas[0])
    if reset_target is None:
        return None
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                finding.path,
                "rev-list",
                "--reverse",
                "--parents",
                f"{reset_target}..{observed_head}",
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

    commit_parents: list[tuple[str, str]] = []
    previous = reset_target
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) != 2:
            # Root commits and merges cannot be safely represented by a single
            # parent reset range.
            return None
        sha, parent = fields
        if parent != previous:
            return None
        commit_parents.append((sha, parent))
        previous = sha

    proved_shas = tuple(sha for sha, _parent in commit_parents)
    if proved_shas != commit_shas or previous != observed_head:
        # Any filtered foreign or host-recorded commit, merge side, missing
        # finding, or later commit makes this reset range unowned.
        return None

    touched_paths = _commit_paths(finding.path, commit_parents)
    if touched_paths is None:
        return None
    return _AbsorptionProof(
        observed_head=observed_head,
        reset_target=reset_target,
        touched_paths=touched_paths,
    )


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


def _head_commit_id(repo_path: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "--verify", "HEAD"],
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


def _commit_parent(repo_path: str, sha: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "--verify", f"{sha}^"],
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


def _commit_paths(
    repo_path: str,
    commit_parents: tuple[tuple[str, str], ...] | list[tuple[str, str]],
) -> frozenset[str] | None:
    """Collect paths touched by each commit, retaining both rename sides."""

    paths: set[str] = set()
    for sha, parent in commit_parents:
        try:
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    repo_path,
                    "diff-tree",
                    "--no-commit-id",
                    "--no-renames",
                    "--name-only",
                    "-r",
                    "-z",
                    parent,
                    sha,
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
        paths.update(path for path in result.stdout.split("\0") if path)
    return frozenset(paths)


def _protected_paths(root: Path, repo_path: str) -> frozenset[str] | None:
    """Return every path recorded dirty at baseline, regardless of live dirt."""

    try:
        records = load_finalizer_baseline_records(root)
    except Exception:
        return None
    if records is None:
        return None
    normalized = normalize_path(repo_path)
    for record in records:
        if record.path == normalized:
            return frozenset(record.fingerprints)
    return None


def _pin_recovery_ref(repo_path: str, run_id: str, head: str) -> str | None:
    safe_run_id = re.sub(r"[^A-Za-z0-9._-]+", "-", run_id).strip(".-")
    if not safe_run_id:
        return None
    ref = f"{_RAW_COMMIT_RECOVERY_REF_PREFIX}{safe_run_id}"
    pinned = _run_git_mutating(repo_path, ["update-ref", ref, head])
    if pinned is None or pinned.returncode != 0:
        _logger.warning("Could not pin raw-commit recovery ref in %s", repo_path)
        return None
    return ref


__all__ = [
    "AbsorbedRawCommits",
    "RawCommitRepo",
    "absorb_raw_local_commits",
    "unrecorded_local_commits",
]
