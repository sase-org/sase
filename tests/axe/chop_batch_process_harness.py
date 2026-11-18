"""Subprocess acceptance harness for chop-batch interruption and recovery.

The harness replaces only the agent workload with a short-lived child that
writes a durable fake launch receipt. The chop batch store, ordinary replay,
typed admission, restart recovery, notification store, and lumberjack SIGTERM
handler remain production code.

Run the disposable manual demonstration with::

    python -m tests.axe.chop_batch_process_harness demo
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import tests.axe._chop_batch_process_cancel as cancellation_scenarios
import tests.axe._chop_batch_process_ordinary as ordinary_scenarios
import tests.axe._chop_batch_process_typed as typed_scenarios
from tests.axe._chop_batch_process_support import HARNESS_ENV

__all__ = ["HARNESS_ENV", "run_scenario", "run_demo", "main"]


def run_scenario(root: Path, scenario: str) -> dict[str, Any]:
    """Run one disposable subprocess acceptance scenario and return evidence."""
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.environ["SASE_HOME"] = str(root / "state")
    n = 4
    from sase.axe import chop_batch_store  # noqa: F401
    from sase.axe.chop_batch_recovery import cancel_chop_batches_for_clan  # noqa: F401
    from sase.axe.state import read_chop_run_log_tail  # noqa: F401
    from sase.notifications.store import load_notifications  # noqa: F401

    if scenario.startswith("ordinary-k-") or scenario in {
        "spawn-before-ack",
        "reserved-before-spawn",
        "sigterm-pause",
        "race",
        "two-episodes",
    }:
        return ordinary_scenarios.run_ordinary_scenario(root, scenario, n)
    if scenario in {
        "cancel-paused",
        "cancel-active",
        "cancel-during-recovery",
        "multi-clan",
    }:
        return cancellation_scenarios.run_cancellation_scenario(root, scenario, n)
    if scenario in {
        "typed-sigterm-pause",
        "typed-kill",
        "typed-cancel-paused",
        "typed-race",
    }:
        return typed_scenarios.run_typed_scenario(root, scenario, n)
    raise ValueError(f"unknown acceptance scenario {scenario!r}")


def run_demo(root: Path) -> dict[str, Any]:
    evidence = {
        "manual_stop_resume": run_scenario(root / "stop-resume", "spawn-before-ack"),
        "manual_clan_kill": run_scenario(root / "clan-kill", "cancel-paused"),
    }
    return evidence


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "demo":
        with tempfile.TemporaryDirectory(prefix="sase-chop-batch-demo-") as temp:
            print(json.dumps(run_demo(Path(temp)), indent=2, sort_keys=True))
        return 0
    raise SystemExit("usage: python -m tests.axe.chop_batch_process_harness demo")


if __name__ == "__main__":
    raise SystemExit(main())
