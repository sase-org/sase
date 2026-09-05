"""The scratch-file resource probe reports the state behind the errno."""

from __future__ import annotations

import os
import resource

from tests._scratch_resource_probe import scratch_resource_report


_HEADROOM = 40


def test_report_covers_every_scratch_resource_when_nothing_is_exhausted() -> None:
    report = scratch_resource_report()

    for label in (
        "TMPDIR env",
        "tmpdir state",
        "filesystem",
        "RLIMIT_NOFILE",
        "open descriptors",
        "descriptor targets",
        "tempfile.TemporaryFile()",
        "os.dup() of a scratch fd",
    ):
        assert f"  {label}: " in report
    assert "tempfile.TemporaryFile(): ok" in report
    assert "os.dup() of a scratch fd: ok" in report


def test_report_names_emfile_when_descriptors_are_exhausted() -> None:
    # EMFILE at these two syscalls is what sase-core's
    # CommitLogFailure::Scratch now reports as "Too many open files (os error
    # 24)" -- errno agreement is the point, not the surrounding prose.
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    held: list[int] = []
    try:
        fd_dir = "/proc/self/fd" if os.path.exists("/proc/self/fd") else "/dev/fd"
        limit = len(os.listdir(fd_dir)) + _HEADROOM
        resource.setrlimit(resource.RLIMIT_NOFILE, (limit, hard))
        while True:
            try:
                held.append(os.open(os.devnull, os.O_RDONLY))
            except OSError:
                break
        report = scratch_resource_report()
    finally:
        for descriptor in held:
            os.close(descriptor)
        resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))

    assert "tempfile.TemporaryFile(): FAILED errno=24" in report
    assert "os.dup() of a scratch fd: FAILED errno=24" in report
