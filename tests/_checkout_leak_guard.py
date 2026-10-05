"""Session-scoped guard against leaks into the suite's own checkout.

Snapshots the checkout running the suite at session start (``git rev-parse
HEAD`` plus ``git status`` for ``sdd``) and compares at session finish. A leak
is either a new commit authored by the test hermetic identity
(``sase-test@example.invalid``) or ``sase@localhost`` (the SDD-init identity),
or any new ``sdd`` status entry. Commits with other identities are only a
note, never a failure. The guard is inert when the suite root is not a git
checkout, on xdist workers, or when explicitly disabled.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

DISABLED_ENV = "SASE_CHECKOUT_LEAK_GUARD_DISABLED"

_TEST_IDENTITY_EMAILS = frozenset({"sase-test@example.invalid", "sase@localhost"})

_BASELINE_ATTRIBUTE = "_sase_checkout_leak_baseline"
_REPORT_ATTRIBUTE = "_sase_checkout_leak_report"

_REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class CheckoutCommit:
    """One commit in ``start..HEAD`` with its identities."""

    sha: str
    author_email: str
    committer_email: str
    subject: str


@dataclass(frozen=True)
class CheckoutSnapshot:
    """Session-start/finish state for the suite checkout."""

    disabled: bool = False
    head: str | None = None
    sdd_entries: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class CheckoutLeak:
    """Classified leak between two snapshots."""

    test_commits: tuple[CheckoutCommit, ...] = ()
    new_sdd_entries: tuple[str, ...] = ()
    foreign_commits: tuple[CheckoutCommit, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.test_commits or self.new_sdd_entries)


def is_test_identity_email(email: str) -> bool:
    """Return true for the hermetic test and SDD-init commit identities."""
    return email.strip() in _TEST_IDENTITY_EMAILS


def _run_git(
    repo_root: Path, *args: str, timeout: float = 30.0
) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def git_head(repo_root: Path) -> str | None:
    """Return the current HEAD sha, or None when unavailable."""
    result = _run_git(repo_root, "rev-parse", "HEAD")
    if result is None or result.returncode != 0:
        return None
    head = result.stdout.strip()
    return head or None


def git_sdd_entries(repo_root: Path) -> frozenset[str] | None:
    """Return the ``sdd`` status entries, or None when not a git checkout."""
    result = _run_git(
        repo_root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--",
        "sdd",
    )
    if result is None or result.returncode != 0:
        return None
    raw = result.stdout
    if not raw:
        return frozenset()
    return frozenset(entry for entry in raw.split("\0") if entry)


def take_checkout_snapshot(repo_root: Path = _REPO_ROOT) -> CheckoutSnapshot:
    """Snapshot HEAD and ``sdd`` status for *repo_root*.

    A root that is not a git checkout disables the guard silently.
    """
    head_result = _run_git(repo_root, "rev-parse", "--git-dir")
    if head_result is None or head_result.returncode != 0:
        return CheckoutSnapshot(disabled=True)
    head = git_head(repo_root)
    entries = git_sdd_entries(repo_root)
    if entries is None:
        return CheckoutSnapshot(disabled=True)
    return CheckoutSnapshot(disabled=False, head=head, sdd_entries=entries)


def collect_range_commits(
    repo_root: Path, start_head: str | None
) -> list[CheckoutCommit]:
    """Return commits in ``start_head..HEAD`` with author/committer emails."""
    if not start_head:
        return []
    end = git_head(repo_root)
    if end is None or end == start_head:
        return []
    result = _run_git(
        repo_root,
        "log",
        "--format=%H%x00%ae%x00%ce%x00%s",
        f"{start_head}..HEAD",
    )
    if result is None or result.returncode != 0:
        return []
    commits: list[CheckoutCommit] = []
    for line in result.stdout.splitlines():
        parts = line.split("\0")
        if len(parts) != 4:
            continue
        sha, author_email, committer_email, subject = parts
        commits.append(
            CheckoutCommit(
                sha=sha,
                author_email=author_email,
                committer_email=committer_email,
                subject=subject,
            )
        )
    return commits


def find_new_sdd_entries(start: frozenset[str], end: frozenset[str]) -> tuple[str, ...]:
    """Return the ``sdd`` status entries that appeared after start."""
    return tuple(sorted(end - start))


def classify_checkout_change(
    start: CheckoutSnapshot,
    end: CheckoutSnapshot,
    range_commits: list[CheckoutCommit],
) -> CheckoutLeak | None:
    """Classify start/finish snapshots; None means no leak to report.

    A disabled snapshot never leaks. Test-identity commits and new ``sdd``
    entries are leaks; foreign-identity commits are carried for the summary
    note only.
    """
    if start.disabled or end.disabled:
        return None
    test_commits = tuple(
        commit
        for commit in range_commits
        if is_test_identity_email(commit.author_email)
        or is_test_identity_email(commit.committer_email)
    )
    foreign_commits = tuple(
        commit for commit in range_commits if commit not in test_commits
    )
    new_sdd = find_new_sdd_entries(start.sdd_entries, end.sdd_entries)
    leak = CheckoutLeak(
        test_commits=test_commits,
        new_sdd_entries=new_sdd,
        foreign_commits=foreign_commits,
    )
    if not leak:
        return None
    return leak


def format_checkout_leak_report(leak: CheckoutLeak, *, start_head: str | None) -> str:
    """Return a failure message naming the offending commits and paths."""
    lines = ["The test suite leaked into its own checkout:"]
    for commit in leak.test_commits:
        lines.append(
            f"  commit {commit.sha[:12]} {commit.author_email}/"
            f"{commit.committer_email} {commit.subject}"
        )
    for entry in leak.new_sdd_entries:
        lines.append(f"  sdd change: {entry}")
    if leak.foreign_commits:
        lines.append(
            f"  note: {len(leak.foreign_commits)} foreign-identity commit(s) "
            "also appeared (not a failure):"
        )
        for commit in leak.foreign_commits[:5]:
            lines.append(f"    {commit.sha[:12]} {commit.subject}")
    if start_head:
        lines.append(
            "Recover with: "
            f"`git reset --keep {start_head}`, then delete the listed paths."
        )
    else:
        lines.append(
            "Recover with: `git reset --keep <start-sha>`, then delete "
            "the listed paths."
        )
    lines.append(f"Set {DISABLED_ENV}=1 to bypass this guard while debugging.")
    return "\n".join(lines)


def format_foreign_commit_note(
    foreign_commits: tuple[CheckoutCommit, ...],
) -> str:
    """Return a summary note for foreign-identity commits (never a failure)."""
    lines = [
        f"note: {len(foreign_commits)} foreign-identity commit(s) appeared "
        "during the suite (not a failure):"
    ]
    for commit in foreign_commits[:5]:
        lines.append(f"  {commit.sha[:12]} {commit.subject}")
    return "\n".join(lines)


def start_checkout_leak_guard(session: pytest.Session) -> None:
    """Record the baseline checkout state for this session."""
    config = session.config
    if _is_guard_exempt(config):
        return
    setattr(config, _BASELINE_ATTRIBUTE, take_checkout_snapshot())


def finish_checkout_leak_guard(session: pytest.Session) -> None:
    """Fail the session when the suite leaked commits or ``sdd`` writes."""
    config = session.config
    baseline = getattr(config, _BASELINE_ATTRIBUTE, None)
    if baseline is None:
        return
    delattr(config, _BASELINE_ATTRIBUTE)
    if not isinstance(baseline, CheckoutSnapshot) or baseline.disabled:
        return
    final = take_checkout_snapshot()
    if final.disabled:
        return
    if final.head != baseline.head:
        range_commits = collect_range_commits(_REPO_ROOT, baseline.head)
    else:
        range_commits = []
    leak = classify_checkout_change(baseline, final, range_commits)
    if leak is not None:
        setattr(
            config,
            _REPORT_ATTRIBUTE,
            format_checkout_leak_report(leak, start_head=baseline.head),
        )
        if session.exitstatus == pytest.ExitCode.OK:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
        return
    if range_commits:
        setattr(
            config,
            _REPORT_ATTRIBUTE,
            format_foreign_commit_note(tuple(range_commits)),
        )


def report_checkout_leak_guard(
    config: pytest.Config, terminalreporter: pytest.TerminalReporter
) -> None:
    """Print the recorded checkout-leak report, if any, in the summary."""
    report = getattr(config, _REPORT_ATTRIBUTE, None)
    if report is None:
        return
    delattr(config, _REPORT_ATTRIBUTE)
    is_failure = report.startswith("The test suite leaked")
    if is_failure:
        terminalreporter.write_sep("=", "checkout leakage", red=True, bold=True)
    else:
        terminalreporter.write_sep("=", "checkout notes")
    terminalreporter.write_line(report)


def _is_guard_exempt(config: pytest.Config) -> bool:
    # xdist workers share the controller's checkout and finish while siblings
    # are still running, so only the controller compares snapshots.
    return os.environ.get(DISABLED_ENV, "") not in ("", "0") or hasattr(
        config, "workerinput"
    )
