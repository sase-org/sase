"""Handler for ``sase plan propose <plan_file>``."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import NoReturn, cast

from sase.main.utils import kill_agent_runner_group


def _read_agent_meta_associations(artifacts_dir: str) -> dict[str, str]:
    """Read durable bead-work associations for the proposing agent."""
    try:
        raw_meta = json.loads(
            (Path(artifacts_dir) / "agent_meta.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(raw_meta, dict):
        return {}

    associations: dict[str, str] = {}
    for key in ("phase_bead_id", "epic_bead_id", "epic_plan_ref", "bead_id"):
        value = raw_meta.get(key)
        if isinstance(value, str) and (stripped := value.strip()):
            associations[key] = stripped
    return associations


def handle_plan_propose_command(plan_file: str) -> NoReturn:
    """Submit a plan file for approval (used by /sase_plan skill).

    1. Guard: verify SASE_AGENT and SASE_ARTIFACTS_DIR env vars
    2. Validate plan_file exists
    3. Validate the authored plan tier (and any pinned auto-approval tier)
    4. Move plan into the ~/.sase/plans/ archive (consumes the scratch file)
    5. Write .sase_plan_pending marker JSON to SASE_ARTIFACTS_DIR
    6. Kill the agent runner's process group via SIGTERM
    """
    # Guard: must be running inside sase agent
    if not os.environ.get("SASE_AGENT"):
        print(
            "Error: 'sase plan propose' is only available inside sase"
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

    # Validate before formatting or making any queue-related mutation.  A
    # pinned tale/epic auto action is the target tier so the core validator
    # emits its authoritative tier-mismatch diagnostic and target schema.
    from sase.main.plan_approve_handler import (
        get_auto_plan_approval_action,
        get_auto_plan_approval_argument,
    )
    from sase.main.plan_validate_handler import read_and_validate_plan_file
    from sase.main.plan_validate_render import render_validation_human
    from sase.output import error_console
    from sase.sdd.plan_tiers import read_plan_tier
    from sase.sdd.plan_validate import plan_frontmatter_schema

    authored_tier = read_plan_tier(plan_path)
    target_tier = authored_tier or "tale"
    validation = read_and_validate_plan_file(plan_path, tier=target_tier)
    if not validation.ok:
        render_validation_human(
            validation,
            tier=target_tier,
            path=plan_file,
            schema=plan_frontmatter_schema(target_tier),
            console=error_console,
        )
        sys.exit(1)
    auto_action = get_auto_plan_approval_action()
    if auto_action is not None:
        from sase.notification_gates.models import GateError
        from sase.plan_gate import PlanGateTier, validate_plan_auto_argument

        auto_argument = get_auto_plan_approval_argument()
        if auto_argument is None and auto_action in {"tale", "epic"}:
            auto_argument = auto_action
        try:
            validate_plan_auto_argument(
                cast(PlanGateTier, target_tier),
                auto_argument,
            )
        except GateError as exc:
            print(
                f"Error [{exc.code.replace('_', '-')}]: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)

    # Plans proposed from bead work inherit managed associations from the
    # proposing agent's active bead: its phase bead, else its epic bead, else
    # the bead the agent itself is working.  The runner intentionally pops the
    # epic-work env vars in ``epic_work_metadata_from_env`` before spawning the
    # CLI while leaving ``SASE_BEAD_ID`` available for commit attribution, so
    # every field keeps the same env-then-durable-metadata fallback.  Tales
    # record the active bead and parent epic plan; child epics record the
    # active bead as ``parent_bead`` and the same parent plan.
    from sase.bead.work import (
        SASE_BEAD_ID_ENV,
        SASE_EPIC_BEAD_ID_ENV,
        SASE_EPIC_PLAN_REF_ENV,
        SASE_PHASE_BEAD_ID_ENV,
    )

    meta_associations = _read_agent_meta_associations(artifacts_dir)
    phase_bead = os.environ.get(
        SASE_PHASE_BEAD_ID_ENV, ""
    ).strip() or meta_associations.get("phase_bead_id", "")
    epic_bead = os.environ.get(
        SASE_EPIC_BEAD_ID_ENV, ""
    ).strip() or meta_associations.get("epic_bead_id", "")
    parent_plan = os.environ.get(
        SASE_EPIC_PLAN_REF_ENV, ""
    ).strip() or meta_associations.get("epic_plan_ref", "")
    agent_bead = os.environ.get(SASE_BEAD_ID_ENV, "").strip() or meta_associations.get(
        "bead_id", ""
    )
    active_bead = phase_bead or epic_bead or agent_bead
    stamps: dict[str, str] = {}
    from sase.bead.attribution import acting_agent_name

    if proposed_by := acting_agent_name():
        stamps["proposed_by"] = proposed_by
    if target_tier == "tale" and active_bead:
        stamps["bead"] = active_bead
    elif target_tier == "epic" and active_bead:
        stamps["parent_bead"] = active_bead

    # Format plan file in-place with prettier before archiving.  Stamp the
    # managed association first so the archived copy is fully formatted.
    from sase.file_references import format_with_prettier

    original = plan_path.read_text(encoding="utf-8")
    raw = original
    if stamps:
        from sase.sdd.frontmatter import set_frontmatter_fields

        raw = set_frontmatter_fields(raw, stamps)
    if parent_plan:
        from sase.sdd.plan_header_writes import upsert_parent_plan_section

        raw = upsert_parent_plan_section(raw, parent_plan)
    if "bead" in stamps:
        from sase.sdd.plan_header_writes import refresh_bead_plan_section

        raw = refresh_bead_plan_section(raw)
    formatted = format_with_prettier(raw)
    if formatted != original:
        plan_path.write_text(formatted, encoding="utf-8")

    # Move plan into the ~/.sase/plans/ archive, consuming the scratch file.
    from sase.llm_provider._plan_utils import move_plan_to_sase

    archived_path = move_plan_to_sase(str(plan_path))

    # Write .sase_plan_pending marker JSON. ``plan_file`` points at the durable
    # archive copy; ``original_file`` is retained for provenance/debugging even
    # though the scratch file no longer exists after the move above.
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

    # Pulse a file at a path the ACE inotify watcher actually sees.
    # ``ArtifactWatcher`` is non-recursive and only watches direct children of
    # ``<project>/artifacts/``; the marker write three levels deeper never
    # wakes it, so the Agents tab waits up to ``FULL_SANITY_REFRESH_SECONDS``
    # to reflect ``PLAN``.  Touching this pulse fires ``IN_MODIFY`` /
    # ``IN_CREATE`` and triggers an async refresh within the coalesce window.
    pulse_path = Path(artifacts_dir).parents[1] / ".ace_refresh_pulse"
    try:
        pulse_path.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass

    # Kill the agent runner's process group (which includes the claude
    # subprocess). We cannot use our own process group because Claude Code
    # spawns Bash-tool subprocesses in an isolated process group; the SIGTERM
    # would never reach `claude` or the agent runner.
    kill_agent_runner_group(artifacts_dir)
