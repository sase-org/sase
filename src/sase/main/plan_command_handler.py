"""Handler for ``sase plan <plan_file>`` CLI subcommand."""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import NoReturn


def handle_plan_command(plan_file: str) -> NoReturn:
    """Submit a plan file for approval (used by /sase_plan skill).

    1. Guard: verify SASE_AGENT and SASE_ARTIFACTS_DIR env vars
    2. Validate plan_file exists
    3. Archive plan to ~/.sase/plans/
    4. Write .sase_plan_pending marker JSON to SASE_ARTIFACTS_DIR
    5. Install no-op SIGTERM handler
    6. Kill process group via SIGTERM
    """
    # Guard: must be running inside sase agent
    if not os.environ.get("SASE_AGENT"):
        print(
            "Error: 'sase plan' is only available inside sase"
            " (SASE_AGENT env var not set).",
            file=sys.stderr,
        )
        sys.exit(1)

    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        print(
            "Error: SASE_ARTIFACTS_DIR env var not set.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Validate plan file exists
    plan_path = Path(plan_file).resolve()
    if not plan_path.is_file():
        print(f"Error: plan file not found: {plan_file}", file=sys.stderr)
        sys.exit(1)

    # Archive plan to ~/.sase/plans/
    from sase.llm_provider._plan_utils import save_plan_to_sase

    archived_path = save_plan_to_sase(str(plan_path))

    # Write .sase_plan_pending marker JSON
    marker_path = Path(artifacts_dir) / ".sase_plan_pending"
    marker_data = {
        "plan_file": str(archived_path),
        "original_file": str(plan_path),
        "timestamp": time.time(),
    }
    with open(marker_path, "w", encoding="utf-8") as f:
        json.dump(marker_data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())

    # Install no-op SIGTERM handler so this process survives its own killpg
    signal.signal(signal.SIGTERM, signal.SIG_IGN)

    # Kill process group
    os.killpg(os.getpgrp(), signal.SIGTERM)
    sys.exit(0)
