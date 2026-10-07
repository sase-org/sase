#!/usr/bin/env python3
"""Wait dependency resolution chop script.

Walks waiting.json markers first and exits no_op before building any
dependency view when no live waiter is pending. Live waiters resolve
through a filesystem view of agent metadata; waiters whose runner is
provably dead are skipped and counted in the dead-waiter backlog
counter. ``SASE_CHOP_SCAN_FULL_WALK=1`` still switches bead_claim_checks
to its legacy full walk.
"""

from sase.scripts._chop_wait_checks_run import main

__all__ = ["main"]


if __name__ == "__main__":
    main()
