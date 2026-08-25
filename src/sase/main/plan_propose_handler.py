"""Handler for ``sase plan propose <plan_file>``."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import NoReturn, cast

from sase.agent.pending_handoff import PLAN_PENDING_MARKER
from sase.agent.pending_handoff_write import (
    PendingHandoffError,
    handoff_guard,
    write_pending_handoff_marker,
)
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
    try:
        artifacts_dir = handoff_guard()
    except PendingHandoffError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    # Validate plan file exists
    plan_path = Path(plan_file).resolve()
    if not plan_path.is_file():
        print(f"Error: plan file not found: {plan_file}", file=sys.stderr)
        sys.exit(1)
    try:
        original = plan_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        print(f"Error: cannot read plan file: {exc}", file=sys.stderr)
        sys.exit(1)

    # Validate before formatting or making any queue-related mutation.  A
    # pinned tale/epic auto action is the target tier so the core validator
    # emits its authoritative tier-mismatch diagnostic and target schema.
    from sase.main.plan_approve_handler import (
        get_auto_plan_approval_action,
        get_auto_plan_approval_argument,
    )
    from sase.main.plan_validate_render import render_validation_human
    from sase.output import error_console
    from sase.sdd.artifact_link_inlet import (
        ArtifactLinkFrontmatterInletError,
        parse_plan_artifact_link_inlet,
        publish_plan_artifact_link_inlet,
        validate_plan_artifact_link_inlet,
    )
    from sase.sdd.plan_tiers import read_plan_tier
    from sase.sdd.plan_validate import plan_frontmatter_schema, validate_plan

    authored_tier = read_plan_tier(plan_path)
    target_tier = authored_tier or "tale"
    try:
        link_inlet = parse_plan_artifact_link_inlet(original)
        validate_plan_artifact_link_inlet(link_inlet)
    except ArtifactLinkFrontmatterInletError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    validation = validate_plan(original, target_tier)
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

    raw = link_inlet.content_without_inlet
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
    if link_inlet.entries:
        from sase.core.paths import sase_subdir
        from sase.sdd.plan_refs import canonicalize_plan_reference_from_roots

        source_ref = canonicalize_plan_reference_from_roots(
            archived_path,
            roots=(sase_subdir("plans"),),
        )
        if source_ref is None:
            print(
                f"Error: archived plan has no canonical plan reference: {archived_path}",
                file=sys.stderr,
            )
            sys.exit(1)
        try:
            publish_plan_artifact_link_inlet(
                archived_path,
                source_ref=source_ref,
                inlet=link_inlet,
            )
        except ArtifactLinkFrontmatterInletError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

    _derive_links_for_archived_plan(
        archived_path,
        created_by=proposed_by or os.environ.get("USER") or "unknown",
        artifacts_dir=artifacts_dir,
    )

    # Write .sase_plan_pending marker JSON. ``plan_file`` points at the durable
    # archive copy; ``original_file`` is retained for provenance/debugging even
    # though the scratch file no longer exists after the move above.
    try:
        write_pending_handoff_marker(
            PLAN_PENDING_MARKER,
            {
                "plan_file": str(archived_path),
                "original_file": str(plan_path),
            },
            artifacts_dir=artifacts_dir,
        )
    except PendingHandoffError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

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


def _derive_links_for_archived_plan(
    archived_path: Path, *, created_by: str, artifacts_dir: str
) -> None:
    """Best-effort: derive candidate links (e.g. `implements` from `bead:`).

    Proposing a plan terminates the runner mechanically, so this is the only
    place a handoff can be caught at all -- a finalizer or a later
    commit-triggered hook never runs for this turn. Never raises: a
    derivation failure must not block a plan handoff.
    """

    from sase.artifact_links.derive import artifact_link_derivation_enabled

    if not artifact_link_derivation_enabled():
        return
    try:
        from sase.artifact_links.derive import DerivableDocument
        from sase.sdd.artifact_link_derivation import derive_and_persist_artifact_links
        from sase.sdd.artifact_link_store import resolve_artifact_link_store
        from sase.sdd.plan_refs import canonicalize_plan_reference_from_roots

        link_store = resolve_artifact_link_store()
        plans_root = link_store.sidecar_roots.get("plan")
        ref = (
            None
            if plans_root is None
            else canonicalize_plan_reference_from_roots(
                archived_path, roots=(plans_root,)
            )
        )
        if ref is not None:
            derive_and_persist_artifact_links(
                link_store,
                (DerivableDocument(ref=ref, path=archived_path),),
                created_by=created_by,
                artifacts_dir=artifacts_dir,
            )
    except Exception:
        pass
