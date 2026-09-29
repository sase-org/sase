#!/usr/bin/env python3
"""Wait dependency resolution chop script.

Consults waiting.json markers first and exits no_op before loading
agent_meta.json when nothing is pending. Remaining waits resolve through
the agent artifact index when it is present, else a targeted filesystem
read of referenced artifacts. ``SASE_CHOP_SCAN_FULL_WALK=1`` restores the
legacy full O(all-artifacts) meta walk for parity testing.
"""

from sase.scripts._chop_wait_checks_run import main

__all__ = ["main"]


if __name__ == "__main__":
    main()
