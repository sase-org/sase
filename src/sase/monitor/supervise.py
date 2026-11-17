"""Detached supervisor for one monitor agent-session member.

Invoked as ``python -m sase.monitor.supervise --artifacts-dir <dir>``, mirroring
:mod:`sase.procs.supervisor`. Owns the monitored command from spawn through the
terminal marker: streams its merged output, enforces the timeout, and reacts
to ``SIGTERM`` (sent by :func:`sase.monitor.store.stop_monitor`) by killing
the command's whole process group rather than just itself.

This module is a facade: it owns no supervisor logic itself and only
re-exports the name its callers have always imported from here. The
orchestration lives in :mod:`sase.monitor.supervise_run`, process control in
:mod:`sase.monitor.supervise_proc`, and terminal settlement in
:mod:`sase.monitor.supervise_finish`.
"""

from __future__ import annotations

import argparse

from .supervise_run import run_supervisor

__all__ = [
    "run_supervisor",
]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Supervise one SASE monitor member.")
    parser.add_argument("--artifacts-dir", required=True)
    return parser


def _main() -> int:
    return run_supervisor(_parser().parse_args().artifacts_dir)


if __name__ == "__main__":
    raise SystemExit(_main())
