"""Session-scoped guard against temporary-directory leakage.

The suite used to strand thousands of ``.lock``, ``-archive``, and bare
``tmpXXXXXXXX`` entries in the shared system temp directory, and to add
directories to the developer's managed SASE temp root. Once those leaks were
fixed, nothing stopped them from coming back silently, so this guard snapshots
the watched temp roots at session start, compares them at session finish, and
fails the run while naming the entries that appeared.
"""

from __future__ import annotations

import fnmatch
import os
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path

import pytest
from sase.core.paths import _unsandboxed_managed_tmpdir_root


DISABLED_ENV = "SASE_TMP_LEAK_GUARD_DISABLED"
IGNORE_ENV = "SASE_TMP_LEAK_GUARD_IGNORE"

# Entries that appear during a run without the suite leaking them: pytest's own
# scratch trees, the host-global worker-token pool, and scratch belonging to
# other processes that happen to share the system temp directory.
FOREIGN_ENTRY_PATTERNS: tuple[str, ...] = (
    ".ICE-unix",
    ".Test-unix",
    ".Trash-*",
    ".X11-unix",
    ".XIM-unix",
    ".font-unix",
    ".org.chromium.*",
    # Agent-launch and ACE-profile scratch in the shared managed temp root
    # (see also "ace-profiles", "launch-prompts", "sase_ace_prompt_*"). Live
    # sase processes elsewhere on this host launch agents and profile the TUI
    # while the suite runs, and they write straight into the same root the
    # developer configured. The suite itself can no longer produce these,
    # because get_sase_managed_tmpdir() sandboxes its root under pytest.
    "ace-profiles",
    "ace_profile_*",
    "check.log",
    "claude-*",
    "dbus-*",
    # Third-party pytest plugin scratch, created at plugin-configure time during
    # healthy runs and later swept by tools/run_pytest's stale scratch reaper.
    "inline-snapshot-*",
    "launch-prompts",  # see "ace_profile_*"
    "node-compile-cache",
    "plainci-*",
    "pytest-of-*",
    "sase-pytest-tokens-*",
    "sase_ace_prompt_*",  # see "ace_profile_*"
    "snap-private-tmp",
    "snap.*",
    "ssh-*",
    "systemd-private-*",
    # mktemp(1) scratch from unrelated host tooling. Python's tempfile never
    # puts a dot after its "tmp" prefix, so this cannot mask a suite leak.
    "tmp.*",
    "tmux-*",
)

_MAX_REPORTED_ENTRIES = 20
_BASELINE_ATTRIBUTE = "_sase_tmp_leak_baseline"
_REPORT_ATTRIBUTE = "_sase_tmp_leak_report"

TempSnapshot = dict[Path, frozenset[str]]


def watched_temp_directories() -> tuple[Path, ...]:
    """Return the temp roots this guard watches.

    The first is the temp directory the suite itself resolves, which is the
    disk-backed scratch root while ``tools/run_pytest`` redirects ``TMPDIR``
    and the real system temp directory otherwise. Every leak reaches it,
    because that is where ``tempfile`` puts an unqualified temp file. The
    shared ``/tmp`` is deliberately not watched on top of it: many sase
    workspaces, editors, and agents write there concurrently, so diffing it
    reports other processes' scratch instead of this suite's.

    The second is the developer's real managed temp root
    (``$SASE_TMPDIR``, else ``~/.sase/tmp``), which
    :func:`sase.core.paths.get_sase_managed_tmpdir` now redirects into the
    pytest sandbox, so the suite should add nothing to it. Only its top level
    is diffed: its category children (``handoff/``, ``wrappers/``,
    ``workflow-artifacts/``, ...) are written continuously by other sase
    processes sharing the root, so watching them would report their scratch
    for the same reason the shared ``/tmp`` is left alone.
    """
    roots: list[Path] = []
    for candidate in (
        Path(tempfile.gettempdir()),
        _unsandboxed_managed_tmpdir_root(),
    ):
        try:
            root = candidate.resolve()
        except OSError:  # pragma: no cover - defensive path resolution
            continue
        if root.is_dir() and root not in roots:
            roots.append(root)
    return tuple(roots)


def snapshot_temp_entries(directories: Iterable[Path]) -> TempSnapshot:
    """Return the names each watched directory holds for the current user."""
    return {directory: _owned_entry_names(directory) for directory in directories}


def ignore_patterns(environ: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """Return the built-in foreign-entry patterns plus any configured ones."""
    source = os.environ if environ is None else environ
    configured = source.get(IGNORE_ENV, "")
    extra = tuple(
        pattern.strip()
        for pattern in configured.replace(os.pathsep, ",").split(",")
        if pattern.strip()
    )
    return FOREIGN_ENTRY_PATTERNS + extra


def find_leaked_entries(
    baseline: TempSnapshot,
    final: TempSnapshot,
    *,
    patterns: Iterable[str] = FOREIGN_ENTRY_PATTERNS,
) -> dict[Path, tuple[str, ...]]:
    """Return the entries that appeared per directory, minus ignored names."""
    ignored = tuple(patterns)
    leaks: dict[Path, tuple[str, ...]] = {}
    for directory, names in final.items():
        added = sorted(names - baseline.get(directory, frozenset()))
        offenders = tuple(
            name for name in added if not _is_ignored_entry(name, ignored)
        )
        if offenders:
            leaks[directory] = offenders
    return leaks


def format_leak_report(leaks: Mapping[Path, tuple[str, ...]]) -> str:
    """Return a failure message naming the entries the suite left behind."""
    lines = ["The test suite left new entries in a watched temp directory:"]
    for directory, names in sorted(leaks.items()):
        lines.append(f"  {directory} ({len(names)} new):")
        for name in names[:_MAX_REPORTED_ENTRIES]:
            lines.append(f"    - {name}")
        remaining = len(names) - _MAX_REPORTED_ENTRIES
        if remaining > 0:
            lines.append(f"    ... and {remaining} more")
    lines.append(
        "Route temporary files through pytest's tmp_path/tmp_path_factory, or "
        "pass an explicit dir= so sase's sibling files are collected with them. "
        "Entries under the managed SASE temp root mean something bypassed "
        "get_sase_managed_tmpdir(), which sandboxes itself under pytest."
    )
    lines.append(f"Set {DISABLED_ENV}=1 to bypass this guard while debugging.")
    return "\n".join(lines)


def start_tmp_leak_guard(session: pytest.Session) -> None:
    """Record the baseline temp-directory contents for this session."""
    config = session.config
    if _is_guard_exempt(config):
        return
    setattr(
        config,
        _BASELINE_ATTRIBUTE,
        snapshot_temp_entries(watched_temp_directories()),
    )


def finish_tmp_leak_guard(session: pytest.Session) -> None:
    """Fail the session when the suite added system temp-directory entries."""
    config = session.config
    baseline = getattr(config, _BASELINE_ATTRIBUTE, None)
    if baseline is None:
        return
    delattr(config, _BASELINE_ATTRIBUTE)

    leaks = find_leaked_entries(
        baseline,
        snapshot_temp_entries(baseline),
        patterns=ignore_patterns(),
    )
    if not leaks:
        return

    setattr(config, _REPORT_ATTRIBUTE, format_leak_report(leaks))
    if session.exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def report_tmp_leak_guard(
    config: pytest.Config, terminalreporter: pytest.TerminalReporter
) -> None:
    """Print the recorded leak report, if any, in the terminal summary."""
    report = getattr(config, _REPORT_ATTRIBUTE, None)
    if report is None:
        return
    delattr(config, _REPORT_ATTRIBUTE)
    terminalreporter.write_sep("=", "system temp leakage", red=True, bold=True)
    terminalreporter.write_line(report)


def _is_guard_exempt(config: pytest.Config) -> bool:
    # xdist workers share the controller's temp roots and finish while siblings
    # are still writing, so only the controller compares snapshots.
    return os.environ.get(DISABLED_ENV, "") not in ("", "0") or hasattr(
        config, "workerinput"
    )


def _owned_entry_names(directory: Path) -> frozenset[str]:
    user_id = os.getuid()
    names: set[str] = set()
    try:
        entries = list(os.scandir(directory))
    except OSError:
        return frozenset()
    for entry in entries:
        try:
            owned = entry.stat(follow_symlinks=False).st_uid == user_id
        except OSError:
            continue
        if owned:
            names.add(entry.name)
    return frozenset(names)


def _is_ignored_entry(name: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)
