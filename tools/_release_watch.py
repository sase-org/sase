#!/usr/bin/env python3
"""CLI facade for the stdlib-only release watcher."""

from __future__ import annotations

import sys
from pathlib import Path
from collections.abc import Sequence

from _release_watch_api import (
    BAD_CONCLUSIONS,
    EXIT_CODES,
    GOOD_CONCLUSIONS,
    GhClient,
    GithubReader,
    IN_FLIGHT,
    PROCESS_TIMEOUT,
    SIGNALS,
    ReleasePullRequest,
    SignalFailure,
    Snapshot,
    WatchOptions,
    WatcherError,
    WatcherSignal,
    WorkflowRun,
    default_verdict_path,
    parse_bead_closed,
    parse_run,
    parse_args,
)
from _release_watch_engine import ReleaseWatcher, short_exception

__all__ = [
    "BAD_CONCLUSIONS",
    "EXIT_CODES",
    "GOOD_CONCLUSIONS",
    "GhClient",
    "GithubReader",
    "IN_FLIGHT",
    "PROCESS_TIMEOUT",
    "ReleasePullRequest",
    "ReleaseWatcher",
    "SIGNALS",
    "SignalFailure",
    "Snapshot",
    "WatchOptions",
    "WatcherError",
    "WatcherSignal",
    "WorkflowRun",
    "main",
    "parse_args",
    "parse_bead_closed",
    "parse_run",
    "short_exception",
]


def _fallback_options(argv: Sequence[str]) -> tuple[Path, str | None, bool, bool]:
    values: dict[str, str] = {}
    for index, item in enumerate(argv):
        for name in ("--verdict-file", "--close-bead"):
            if item == name and index + 1 < len(argv):
                values[name] = argv[index + 1]
            elif item.startswith(name + "="):
                values[name] = item.split("=", 1)[1]
    path = (
        Path(values["--verdict-file"])
        if values.get("--verdict-file")
        else default_verdict_path()
    )
    return path, values.get("--close-bead"), "--dry-run" in argv, "--once" in argv


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        options = parse_args(args)
    except SystemExit as exc:
        return int(exc.code or 0)
    except Exception as exc:
        path, close_bead, dry_run, once = _fallback_options(args)
        options = WatchOptions(
            "sase-org/sase",
            "0.18.0",
            "0" * 40,
            1,
            1,
            2,
            dry_run,
            once,
            str(path),
            close_bead,
        )
        watcher = ReleaseWatcher(options, reader=object(), verdict_path=path)
        watcher.set_verdict("WATCHER_BROKEN", f"bad arguments: {short_exception(exc)}")
        return watcher.finalize()
    gh = GhClient(options.repo)
    reader = GithubReader(options.repo, options.version, options.fixed_sha, gh)
    return ReleaseWatcher(options, reader).run()
