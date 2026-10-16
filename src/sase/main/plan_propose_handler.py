"""Handler for ``sase plan propose <plan_file>``."""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn, cast

from sase.agent.pending_handoff import PLAN_PENDING_MARKER
from sase.agent.pending_handoff_write import (
    PendingHandoffError,
    handoff_guard,
    write_pending_handoff_marker,
)
from sase.main.utils import kill_agent_runner_group

if TYPE_CHECKING:
    from sase.sdd.plan_validate import PlanValidationResult

# Longest source line echoed in a formatted-plan error (keeps `tail` readable).
_SOURCE_LINE_LIMIT = 160


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


def _touch_turn_refresh_pulse_for_artifacts_dir(artifacts_dir: str) -> None:
    """Nudge artifact watchers after a plan handoff marker mutation."""
    try:
        from sase.turns.settlement import (
            project_name_from_artifacts_dir,
            touch_turn_refresh_pulse,
        )

        touch_turn_refresh_pulse(project_name_from_artifacts_dir(artifacts_dir))
    except Exception:  # noqa: BLE001 - a refresh pulse must never fail the handoff.
        pass


def _validate_plan_text(
    text: str, target_tier: str, artifacts_dir: str
) -> PlanValidationResult:
    """Validate plan *text* in authoring mode, including decision host checks.

    A failing host check (or an exception from it) comes back as a failed
    result carrying the extra diagnostics, with no validated plan.
    """
    from sase.sdd.plan_validate import PlanValidationResult, validate_plan

    validation = validate_plan(text, target_tier)
    if validation.plan is None or not getattr(
        validation.plan, "decisions", cast(Any, ())
    ):
        return validation

    from sase.sdd.plan_decisions import validate_host_checks

    try:
        extra = validate_host_checks(
            text,
            validation,
            artifacts_dir,
            strict_quotes=True,
        )
    except Exception as exc:
        from sase.sdd.plan_validate import PlanDiagnostic, PlanDiagnosticSeverity

        extra = [
            PlanDiagnostic(
                severity=PlanDiagnosticSeverity.ERROR,
                code="decision-host-check-failed",
                field_path="decisions",
                message=f"plan decision host checks failed: {exc}",
                line=None,
            )
        ]
    if not extra:
        return validation
    return PlanValidationResult(
        schema_version=validation.schema_version,
        ok=False,
        diagnostics=(*validation.diagnostics, *extra),
        plan=None,
    )


_CalloutSignature = tuple[str, str | None, str]


def _callout_signature(validation: PlanValidationResult) -> list[_CalloutSignature]:
    """The ordered ``(id, key, branch)`` of each callout; lines are ignored."""
    callouts = getattr(validation.plan, "decision_callouts", cast(Any, ()))
    return [(c.id, c.key, c.branch) for c in callouts]


def _callout_label(signature: _CalloutSignature) -> str:
    """Render a callout as it is authored: ``id = key`` or ``id = yes|no``."""
    callout_id, key, branch = signature
    return f"{callout_id} = {key or branch}"


def _formatted_plan_failure(
    authored: PlanValidationResult,
    formatted: str,
    target_tier: str,
    artifacts_dir: str,
) -> str | None:
    """Describe how formatting broke an already-valid plan, or ``None``.

    Prettier may reshape the text the agent validated, and the host validates
    the archived copy only after the runner is gone.  This returns a short
    message (agents pipe propose into ``tail``) when the formatted text fails
    validation or its decision callouts differ from the authored ones.
    """
    result = _validate_plan_text(formatted, target_tier, artifacts_dir)
    lines: list[str] = []
    source_lines = formatted.splitlines()
    for diagnostic in result.diagnostics:
        if not diagnostic.is_error:
            continue
        if diagnostic.line is None:
            lines.append(f"formatted [{diagnostic.code}] {diagnostic.message}")
            continue
        lines.append(
            f"formatted line {diagnostic.line} [{diagnostic.code}] {diagnostic.message}"
        )
        if 0 < diagnostic.line <= len(source_lines):
            text = source_lines[diagnostic.line - 1].strip()
            if len(text) > _SOURCE_LINE_LIMIT:
                text = text[: _SOURCE_LINE_LIMIT - 1] + "…"
            lines.append(f"    {text}")
    if result.plan is not None:
        before = _callout_signature(authored)
        after = _callout_signature(result)
        if before != after:
            lost = Counter(before) - Counter(after)
            gained = Counter(after) - Counter(before)
            lines.extend(f"lost callout: {_callout_label(c)}" for c in lost.elements())
            lines.extend(
                f"unexpected callout: {_callout_label(c)}" for c in gained.elements()
            )
            if not lost and not gained:
                lines.append("callouts were reordered")
    if result.ok and not lines:
        return None
    return "\n".join(
        [
            "Error: formatting this plan for the archive would change its "
            "meaning; nothing was proposed.",
            *lines,
            "Give each > [!decision] header its own paragraph or rephrase the "
            "affected text, then rerun sase plan propose.",
        ]
    )


def handle_plan_propose_command(plan_file: str) -> NoReturn:
    """Submit a plan file for approval (used by /sase_plan skill).

    1. Guard: verify SASE_AGENT and SASE_ARTIFACTS_DIR env vars
    2. Validate plan_file exists
    3. Validate the authored plan tier (a pinned auto tier selects coverage;
       a cross-tier pin parks the plan for review)
    4. Format the plan with prettier and re-validate the formatted text: if
       formatting would change validity or the decision callouts, exit 1
       before touching the scratch file, the archive, or the runner
    5. Move plan into the ~/.sase/plans/ archive (consumes the scratch file)
    6. Write .sase_plan_pending marker JSON to SASE_ARTIFACTS_DIR
    7. Kill the agent runner's process group via SIGTERM
    """
    try:
        artifacts_dir = handoff_guard(command="sase plan propose")
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
    # pinned tier selects coverage, so the core validator emits its
    # authoritative tier-mismatch diagnostic and target schema; a cross-tier
    # pin parks the plan for review.
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
    from sase.sdd.plan_validate import plan_frontmatter_schema

    authored_tier = read_plan_tier(plan_path)
    target_tier = authored_tier or "tale"
    try:
        link_inlet = parse_plan_artifact_link_inlet(original)
        validate_plan_artifact_link_inlet(link_inlet)
    except ArtifactLinkFrontmatterInletError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    validation = _validate_plan_text(original, target_tier, artifacts_dir)
    _filtered_schema = plan_frontmatter_schema(target_tier)
    if not validation.ok:
        render_validation_human(
            validation,
            tier=target_tier,
            path=plan_file,
            schema=_filtered_schema,
            console=error_console,
        )
        sys.exit(1)
    auto_action = get_auto_plan_approval_action()
    auto_argument = get_auto_plan_approval_argument()
    if auto_argument is None and auto_action in {"tale", "epic"}:
        auto_argument = auto_action
    from sase._plan_gate_metadata import (
        effective_plan_auto_argument,
        plan_auto_covers_tier,
    )
    from sase.plan_gate import PlanGateTier

    auto_applies = auto_action is not None and plan_auto_covers_tier(
        cast(PlanGateTier, target_tier),
        effective_plan_auto_argument(auto_action, auto_argument),
    )
    if validation.plan is not None and getattr(
        validation.plan, "decisions", cast(Any, ())
    ):
        from sase.sdd.plan_decisions import count_memory as _count_memory

        _n = len(getattr(validation.plan, "decisions", cast(Any, ())))
        _m = _count_memory(getattr(validation.plan, "decisions", cast(Any, ())))
        print(f"Plan Decisions: {_n} (🧠 {_m})")
        if auto_applies:
            print("auto-approved: every decision takes its default")
    if auto_action is not None:
        from sase.notification_gates.models import GateError
        from sase.plan_gate import validate_plan_auto_argument

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
        if not auto_applies:
            display = auto_argument or auto_action or ""
            print(
                f"`%auto:{display}` does not cover {target_tier} plans; "
                "this plan waits for review"
            )

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
    from sase.sdd.plan_project import plan_project_for_artifacts_dir

    if project := plan_project_for_artifacts_dir(artifacts_dir):
        stamps["project"] = project
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

    # The formatted text is what gets archived, and the host re-validates it
    # only after this runner is gone.  Check it here, while the agent can
    # still fix the plan: nothing below this point has run yet, so a failure
    # leaves the scratch file, the archive, and the runner untouched.
    # Archival formats the plan a second time; a first pass that only
    # normalizes emphasis can make the second pass invalid, so check that
    # text too.
    if failure := _formatted_plan_failure(
        validation, formatted, target_tier, artifacts_dir
    ):
        print(failure, file=sys.stderr)
        sys.exit(1)
    if failure := _formatted_plan_failure(
        validation,
        format_with_prettier(formatted),
        target_tier,
        artifacts_dir,
    ):
        print(failure, file=sys.stderr)
        sys.exit(1)
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

    # Publishing the link inlet rewrites the archived copy's managed link
    # blocks, so validate the bytes the host will actually see.  Only the
    # scratch file is consumed by now: put it back as the agent wrote it and
    # drop the archive so the agent can fix the plan and propose again.
    if link_inlet.entries and (
        failure := _formatted_plan_failure(
            validation,
            archived_path.read_text(encoding="utf-8"),
            target_tier,
            artifacts_dir,
        )
    ):
        plan_path.write_text(original, encoding="utf-8")
        archived_path.unlink(missing_ok=True)
        print(failure, file=sys.stderr)
        sys.exit(1)

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

    # Pulse a file at a path the TUI inotify watcher and surface-token probe
    # both see. The marker write deeper in the artifact tree does not reliably
    # wake Agents-tab refreshes, especially for sharded ace-run layouts.
    _touch_turn_refresh_pulse_for_artifacts_dir(artifacts_dir)

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
