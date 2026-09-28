"""Managed one-shot integration worker for sidecar bead stores.

Implementation lives in focused sibling modules. This facade intentionally
keeps the established public import path stable for callers.
"""

from __future__ import annotations

import sys
from pathlib import Path

from sase.bead._sync_worker_run import (
    run_managed_sync_worker as run_managed_sync_worker,
)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 3:
        return 2
    outcome = run_managed_sync_worker(
        Path(args[0]),
        Path(args[1]),
        log_path=Path(args[2]),
    )
    return 0 if outcome.pushed or outcome.skipped_locked else 1


if __name__ == "__main__":
    raise SystemExit(main())
