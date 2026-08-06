"""Shared plan builders for plan-file ``sase bead work`` tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any


EPIC_PLAN = """---
tier: epic
title: Plan-file rollout
goal: Exercise the host-owned plan-file launch.
phases:
  - id: core
    title: Build the core
    depends_on: []
    size: small
  - id: cli
    title: Add the CLI
    depends_on: [core]
    size: medium
  - id: verify
    title: Verify the result
    depends_on: [core, cli]
    size: large
---
# Plan

Execute the rollout.
"""


# ``EPIC_PLAN`` with a hand-authored trailing-text annotation on the
# machine-owned ``PARENT`` header bullet -- the exact mistake that motivated
# the ``header-invalid`` diagnostic (see plan_header_validation.md).
MALFORMED_HEADER_EPIC_PLAN = EPIC_PLAN.replace(
    "---\n# Plan",
    "---\n\n"
    "- **PARENT:** [202608/parent.md](202608/parent.md) (epic sase-1, closed)\n\n"
    "# Plan",
)


def epic_plan_with_parent(parent_id: str) -> str:
    return EPIC_PLAN.replace(
        "goal: Exercise the host-owned plan-file launch.\n",
        f"goal: Exercise the host-owned plan-file launch.\nparent_bead: {parent_id}\n",
    )


def epic_plan_with_phase_count(
    phase_count: int,
    *,
    model: str | None = None,
) -> str:
    model_line = f"model: {model}\n" if model else ""
    phase_lines = "".join(
        f"  - id: phase_{index}\n    title: Phase {index}\n"
        "    depends_on: []\n    size: small\n"
        for index in range(1, phase_count + 1)
    )
    return (
        "---\n"
        "tier: epic\n"
        "title: Threshold preview\n"
        "goal: Preview threshold-aware lander routing.\n"
        f"{model_line}"
        "phases:\n"
        f"{phase_lines}"
        "---\n"
        "# Plan\n"
    )


def write_plan_update(
    _store: Any,
    *,
    workspace_dir: Path,
    plan_path: Path,
    content: str,
    message: str,
) -> bool:
    del workspace_dir, message
    plan_path.write_text(content, encoding="utf-8")
    return True
