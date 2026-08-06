"""Resource probe for the artifact-ref commit inventory's scratch-file failure.

sase-core's ``commit_log_output`` opens an anonymous scratch file for ``git
log`` output and clones its descriptor.  When either step fails it reports
``CommitLogFailure::Scratch``, which since ``sase-core-rs`` 0.18.4 names both
the failing step (create or clone) and the errno behind it. Before that it
discarded the underlying ``io::Error`` and guessed at an unwritable ``TMPDIR``.

That guess was usually wrong. The scratch_tmpdir_leak_fix phase traced one such
empty-inventory CI failure to test pollution, not a bad ``TMPDIR``: an earlier
test on the same xdist worker redirected ``TMPDIR`` without routing the change
through ``monkeypatch``, and the redirect outlived that test's own teardown,
left pointing at a ``tmp_path`` pytest had since deleted. Python's own
``tempfile.gettempdir()`` never noticed, because it caches its answer on first
use -- only non-Python code that re-reads ``$TMPDIR`` on every call, like
sase-core's Rust extension, does. That specific leak is now caught directly by
``tests/_tmp_leak_guard.py``'s per-test guard; this probe stays as a fallback
for the resource-exhaustion causes (EMFILE, ENOSPC, an O_TMPFILE quirk) that
guard cannot catch.

This module reproduces both syscalls from Python and reports the surrounding
resource state. sase-core's errno names *what* failed for one call; the fd
table, ``statvfs`` counters and ``RLIMIT_NOFILE`` recorded here are what say
*why*, and they are only observable from inside the failing process.
"""

from __future__ import annotations

import collections
import os
from pathlib import Path
import resource
import tempfile


_TOP_DESCRIPTOR_TARGETS = 8


def scratch_resource_report() -> str:
    """Return a multi-line report of the scratch-file resource state."""
    lines = ["scratch-probe: resource state at empty commit inventory"]
    for label, value in _report_fields():
        lines.append(f"  {label}: {value}")
    return "\n".join(lines)


def _report_fields() -> list[tuple[str, str]]:
    tmpdir = tempfile.gettempdir()
    fields = [
        ("TMPDIR env", os.environ.get("TMPDIR", "<unset>")),
        ("tempfile.gettempdir()", tmpdir),
        ("tmpdir state", _directory_state(Path(tmpdir))),
        ("filesystem", _filesystem_state(tmpdir)),
        ("RLIMIT_NOFILE", _rlimit_nofile()),
        ("open descriptors", _open_descriptor_count()),
        ("descriptor targets", _open_descriptor_targets()),
        ("tempfile.TemporaryFile()", _probe_temporary_file()),
        ("os.dup() of a scratch fd", _probe_dup()),
    ]
    return fields


def _directory_state(tmpdir: Path) -> str:
    return (
        f"exists={tmpdir.exists()} is_dir={tmpdir.is_dir()} "
        f"writable={os.access(tmpdir, os.W_OK)} "
        f"executable={os.access(tmpdir, os.X_OK)}"
    )


def _filesystem_state(tmpdir: str) -> str:
    try:
        stats = os.statvfs(tmpdir)
    except OSError as error:
        return _describe_error(error)
    free_bytes = stats.f_bavail * stats.f_frsize
    return (
        f"free_bytes={free_bytes} f_bavail={stats.f_bavail} "
        f"f_favail={stats.f_favail} f_files={stats.f_files} "
        f"f_frsize={stats.f_frsize}"
    )


def _rlimit_nofile() -> str:
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    return f"soft={soft} hard={hard}"


def _open_descriptor_count() -> str:
    try:
        entries = os.listdir("/proc/self/fd")
    except OSError as error:
        return _describe_error(error)
    # listdir itself holds a descriptor open while it reads the directory.
    return str(max(len(entries) - 1, 0))


def _open_descriptor_targets() -> str:
    """Summarize what this process's descriptors point at, most common first.

    A descriptor leak is one of the live candidates behind the failure, so the
    shape of the fd table matters as much as its size.
    """
    try:
        entries = os.listdir("/proc/self/fd")
    except OSError as error:
        return _describe_error(error)
    counts: collections.Counter[str] = collections.Counter()
    for entry in entries:
        try:
            counts[os.readlink(f"/proc/self/fd/{entry}")] += 1
        except OSError:
            # The descriptor closed between listing and reading it.
            counts["<vanished>"] += 1
    common = counts.most_common(_TOP_DESCRIPTOR_TARGETS)
    remainder = len(counts) - len(common)
    summary = ", ".join(f"{target} x{count}" for target, count in common)
    if remainder > 0:
        summary += f", (+{remainder} other targets)"
    return summary


def _probe_temporary_file() -> str:
    try:
        with tempfile.TemporaryFile() as handle:
            return f"ok (fd={handle.fileno()})"
    except OSError as error:
        return _describe_error(error)


def _probe_dup() -> str:
    try:
        with tempfile.TemporaryFile() as handle:
            duplicate = os.dup(handle.fileno())
    except OSError as error:
        return _describe_error(error)
    os.close(duplicate)
    return "ok"


def _describe_error(error: OSError) -> str:
    name = os.strerror(error.errno) if error.errno is not None else "unknown"
    return f"FAILED errno={error.errno} ({name}) {error}"
