"""Shutdown and completion helpers for ``run_agent_runner``."""

import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from sase.bead.claims import (
    BeadClaimMarker,
    clear_bead_claim_marker,
    read_bead_claim_marker,
)
from sase.core.agent_artifact_index_lifecycle import (
    sync_dismissed_agent_artifact_index,
)
from sase.core.agent_types import AgentType
from sase.core.dismissed_agents_facade import add_dismissed_agents
from sase.core.dismissed_agent_completion import GATE_OUTCOME, MONITOR_OUTCOME
from sase.axe.run_agent_gate_handoff import gate_handoff_claim_moved
from sase.axe.run_agent_monitor_handoff import monitor_handoff_claim_transferred
from sase.axe.runner_reporting import deferred_commit_details

_NON_HOLD_FAILURE_OUTCOMES = {
    GATE_OUTCOME,
    "killed",
    "failed_retried",
    "plan_rejected",
    "plan_committed",
    "epic_approved",
    "epic_launch_failed",
    "setup_materialization_failed",
    "setup_workspace_failed",
}


@dataclass(frozen=True)
class RunnerShutdownContext:
    project_file: str
    workflow_name: str
    cl_name: str
    artifacts_timestamp: str
    artifacts_dir: str
    output_path: str
    submitted_prompt: str
    prompt: str
    is_home_mode: bool


@dataclass
class RunnerShutdownState:
    success: bool
    duration: str
    workspace_num: int
    workspace_dir: str
    current_artifacts_dir: str
    running_marker_path: str | None
    agent_name: str | None
    agent_model: str | None
    agent_llm_provider: str | None
    agent_hidden: bool
    saved_path: str | None
    diff_path: str | None
    markdown_pdf_paths: list[str]
    markdown_source_count: int
    image_paths: list[str]
    video_paths: list[str]
    step_output: dict[str, Any] | None
    exec_outcome: str
    error_summary: str | None
    error_traceback_str: str | None
    suppress_completion_notification: bool
    runtime: str | None
    held_bead_claim_id: str | None = None
    held_bead_claim_agent: str | None = None
    held_bead_claim_project: str | None = None
    force_silent_notification: bool = False


@dataclass(frozen=True)
class RunnerShutdownDeps:
    update_artifact_index: Callable[[str], Any]
    was_killed: Callable[[], bool]
    all_steps_hidden: Callable[[str], bool]
    write_error_report: Callable[..., str | None]
    write_error_done_marker: Callable[..., Any]
    send_completion_notification: Callable[..., Any]
    auto_dismiss_completed_agent: Callable[[str, str], Any]


def auto_dismiss_completed_agent(cl_name: str, artifacts_timestamp: str) -> None:
    """Persist auto-dismiss identities for a completed background run."""
    try:
        # Dismiss both RUNNING and WORKFLOW identities -- dedup may pick
        # either depending on whether workflow_state.json exists.
        identities = {
            (AgentType.RUNNING, cl_name, artifacts_timestamp),
            (AgentType.WORKFLOW, cl_name, artifacts_timestamp),
        }
        # Merge under the index lock: the TUI and other runners write it too.
        dismissed = add_dismissed_agents(identities)
        sync_dismissed_agent_artifact_index(dismissed, added=identities)
    except Exception:
        pass  # Best effort


def _should_hold_workspace(
    state: RunnerShutdownState,
    *,
    was_killed: bool,
    auto_dismiss: bool,
    steps_hidden: bool,
    has_deferred_commit: bool,
) -> bool:
    """Return whether this run has a visible dismissal path.

    A failed run always needs one. A completed run needs one too when the
    host upheld a commit deferral: the tree is dirty on purpose and someone
    still has to finish the commit by hand.

    Staged turns reach here with ``failed`` after a held adoption (unresolved
    stage, failed finalization, or provider failure), so the existing failed
    branch already retains dirty failed work through the failure hold. An
    explicit user kill discards the stage first, so ``was_killed`` correctly
    releases. Adopted staged turns settle as ordinary completions.
    """
    if state.exec_outcome == "hijacked":
        return True
    if (
        was_killed
        or auto_dismiss
        or steps_hidden
        or state.suppress_completion_notification
    ):
        return False
    if state.success:
        return has_deferred_commit
    return state.exec_outcome not in _NON_HOLD_FAILURE_OUTCOMES


def _held_bead_claim_from_state(
    state: RunnerShutdownState,
) -> BeadClaimMarker | None:
    if (
        state.held_bead_claim_id
        and state.held_bead_claim_agent
        and state.held_bead_claim_project
    ):
        return BeadClaimMarker(
            bead_id=state.held_bead_claim_id,
            agent_name=state.held_bead_claim_agent,
            project_name=state.held_bead_claim_project,
        )
    return None


def _agent_meta_has_promoted_bead_claim(artifacts_dir: str) -> bool:
    try:
        with open(
            os.path.join(artifacts_dir, "agent_meta.json"), encoding="utf-8"
        ) as f:
            payload = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False
    return isinstance(payload, dict) and payload.get("bead_claim_promoted") is True


def _has_staged_handoff(artifacts_dir: str | None) -> bool:
    """Return whether staged state keeps a waiting bead claim.

    An unresolved stage, a held adoption receipt, or malformed staged state
    all keep the claim: the later re-adopt/reconciliation phase owns it, not
    this shutdown.
    """
    if not artifacts_dir:
        return False
    try:
        from sase.agent.staged_handoff import (
            StagedHandoffError,
            read_adoption_receipt,
            read_staged_handoff,
        )

        try:
            if read_staged_handoff(artifacts_dir) is not None:
                return True
        except StagedHandoffError:
            return True
        try:
            return read_adoption_receipt(artifacts_dir) is not None
        except StagedHandoffError:
            return True
    except Exception:  # noqa: BLE001 - shutdown guard fails open.
        return False
    return False


def _settle_failed_staged_workspace(
    *,
    context: RunnerShutdownContext,
    state: RunnerShutdownState,
    write_error_done_marker: Callable[..., Any],
) -> tuple[bool, bool, bool]:
    """Retain failed staged work even when notification policy hides the run.

    The shared Rust policy decides whether work remains. Once a staged failure
    is in scope, this function always suppresses the ordinary cleanup path:
    a stale or unavailable decision must never release a possibly replaced
    claim.
    """
    if state.success or state.exec_outcome != "failed":
        return False, False, False
    try:
        from sase.agent.staged_handoff import (
            StagedHandoffError,
            read_adoption_receipt,
            read_staged_handoff,
        )

        staged_read_failed = False
        try:
            staged_record = read_staged_handoff(context.artifacts_dir)
        except StagedHandoffError:
            staged_record = None
            staged_read_failed = True
        try:
            receipt = read_adoption_receipt(context.artifacts_dir)
        except StagedHandoffError:
            receipt = None
            staged_read_failed = True
    except Exception:  # noqa: BLE001 - no staged contract, keep legacy behavior.
        return False, False, False
    if staged_record is None and receipt is None and not staged_read_failed:
        return False, False, False

    marker_state = replace(state, current_artifacts_dir=context.artifacts_dir)
    _ensure_failed_done_marker(
        context=context,
        state=marker_state,
        write_error_done_marker=write_error_done_marker,
    )
    marker_written = os.path.isfile(os.path.join(context.artifacts_dir, "done.json"))

    staged_id = None
    if isinstance(staged_record, dict):
        staged_id = staged_record.get("staged_id")
    if not isinstance(staged_id, str) and isinstance(receipt, dict):
        staged_id = receipt.get("staged_id")
    staged_id = staged_id if isinstance(staged_id, str) else None
    reason = (
        str(receipt.get("reason"))
        if isinstance(receipt, dict) and receipt.get("reason")
        else state.error_summary
        or (
            "staged handoff record or receipt was malformed"
            if staged_read_failed
            else "staged handoff did not reach a successor"
        )
    )

    try:
        with open(
            os.path.join(context.artifacts_dir, "agent_meta.json"), encoding="utf-8"
        ) as f:
            meta = json.load(f)
        if not isinstance(meta, dict):
            meta = {}
    except (OSError, json.JSONDecodeError):
        meta = {}

    raw_workspace_num = meta.get("workspace_num", state.workspace_num)
    try:
        workspace_num = int(raw_workspace_num or 0)
    except (TypeError, ValueError):
        workspace_num = state.workspace_num
    raw_pid = meta.get("pid")
    pid = (
        raw_pid
        if isinstance(raw_pid, int) and not isinstance(raw_pid, bool)
        else os.getpid()
    )
    raw_cl_name = meta.get("cl_name") or meta.get("patch_name") or context.cl_name
    cl_name = raw_cl_name if isinstance(raw_cl_name, str) else context.cl_name
    raw_checkout = meta.get("workspace_dir") or state.workspace_dir
    checkout_dir = raw_checkout if isinstance(raw_checkout, str) else None
    workflow = context.workflow_name

    try:
        from sase.turns.workspace_retention import (
            WorkspaceRetentionOwner,
            discover_workspace_retention_repos,
            settle_stranded_workspace,
        )

        from sase.running_field import get_claimed_workspaces

        repos, origin_repo_ids = discover_workspace_retention_repos(
            context.artifacts_dir,
            checkout_dir,
        )
        if not workflow:
            matching = [
                claim
                for claim in get_claimed_workspaces(context.project_file)
                if claim.workspace_num == workspace_num
                and claim.pid == pid
                and (claim.cl_name or "") == cl_name
                and (claim.artifacts_timestamp or "") == context.artifacts_timestamp
            ]
            if len(matching) == 1:
                workflow = matching[0].workflow
        owner = WorkspaceRetentionOwner(
            project_file=context.project_file,
            workspace_num=workspace_num,
            workflow=workflow,
            cl_name=cl_name,
            artifacts_timestamp=context.artifacts_timestamp,
            pid=pid,
            artifacts_dir=context.artifacts_dir,
            checkout_dir=checkout_dir,
            repos=repos,
            origin_repo_ids=origin_repo_ids,
            staged_id=staged_id,
            session_id=(
                str(meta.get("agent_session")) if meta.get("agent_session") else None
            ),
            turn_id=str(meta.get("name")) if meta.get("name") else None,
            terminal_reason=reason,
        )
        result = settle_stranded_workspace(owner)
        if result.disposition == "retain":
            return True, result.claim_changed, marker_written
        return True, False, marker_written
    except Exception as exc:  # noqa: BLE001 - uncertainty must keep the claim.
        try:
            from sase.running_field import hold_workspace_claim

            held = hold_workspace_claim(
                context.project_file,
                workspace_num,
                workflow or context.workflow_name,
                cl_name,
                context.artifacts_timestamp,
                caller_tag="staged-retention-fail-closed",
                expected_pid=pid,
            )
            print(
                f"Workspace retention decision failed; claim hold "
                f"{'succeeded' if held.success else 'failed'}: {exc}",
                file=sys.stderr,
            )
            return True, held.success, marker_written
        except Exception as hold_exc:  # noqa: BLE001 - never fall back to release.
            print(
                f"Workspace retention and fail-closed hold failed: {hold_exc}",
                file=sys.stderr,
            )
            return True, False, marker_written


def _held_bead_claim_for_shutdown(
    context: RunnerShutdownContext,
    state: RunnerShutdownState,
) -> BeadClaimMarker | None:
    return _held_bead_claim_from_state(state) or read_bead_claim_marker(
        context.artifacts_dir
    )


def _write_hijacked_done_marker(
    *,
    context: RunnerShutdownContext,
    state: RunnerShutdownState,
) -> None:
    """Write ``outcome: hijacked`` plus pending recovery when none exists."""
    from sase.agent._user_kill_intent import pending_hijack_recovery
    from sase.axe.run_agent_exec_markers import write_done_marker_and_update_index
    from sase.axe.run_agent_phases import build_done_marker

    artifacts_dir = state.current_artifacts_dir
    marker = build_done_marker(
        context.cl_name,
        context.project_file,
        context.artifacts_timestamp,
        context.artifacts_timestamp,
        state.workspace_num,
        state.workspace_dir,
        context.output_path,
        "hijacked",
        agent_name=state.agent_name,
        agent_model=state.agent_model,
        agent_llm_provider=state.agent_llm_provider,
        agent_hidden=state.agent_hidden,
        recovery=pending_hijack_recovery(artifacts_dir),
    )
    write_done_marker_and_update_index(str(artifacts_dir), marker)


def _ensure_failed_done_marker(
    *,
    context: RunnerShutdownContext,
    state: RunnerShutdownState,
    write_error_done_marker: Callable[..., Any],
) -> None:
    """Write a failed ``done.json`` when a hold (or error report) has none.

    A pinned workspace claim with no done marker is invisible to ACE and
    the stale-claim sweep, so a hold must never land without one. Best
    effort: log loudly if the marker still cannot be written.
    """
    artifacts_dir = state.current_artifacts_dir
    done_path = os.path.join(artifacts_dir, "done.json")
    if os.path.isfile(done_path):
        return
    if state.exec_outcome == "hijacked":
        try:
            _write_hijacked_done_marker(context=context, state=state)
        except Exception as exc:
            print(
                f"Error writing hijacked done.json for workspace "
                f"#{state.workspace_num}: {exc}",
                file=sys.stderr,
            )
        if not os.path.isfile(done_path):
            print(
                f"Error: workspace #{state.workspace_num} still has no "
                f"done.json at {done_path}",
                file=sys.stderr,
            )
        return
    error = state.error_summary or "workspace held without a done.json marker"
    traceback_str = state.error_traceback_str or ""
    try:
        from sase.axe.runner_failure_facts import capture_failure_facts
        from sase.axe.runner_lifecycle_phase import current_lifecycle_phase

        failure_facts = capture_failure_facts(
            None,
            phase=current_lifecycle_phase(),
            error_text=error,
            traceback_text=traceback_str or None,
        )
        write_error_done_marker(
            current_artifacts_dir=artifacts_dir,
            cl_name=context.cl_name,
            project_file=context.project_file,
            timestamp=context.artifacts_timestamp,
            artifacts_timestamp=context.artifacts_timestamp,
            workspace_num=state.workspace_num,
            workspace_dir=state.workspace_dir,
            output_path=context.output_path,
            agent_name=state.agent_name,
            agent_model=state.agent_model,
            agent_llm_provider=state.agent_llm_provider,
            agent_vcs_provider=None,
            agent_hidden=state.agent_hidden,
            error=error,
            traceback_str=traceback_str,
            failure_facts=failure_facts,
        )
    except Exception as exc:
        print(
            f"Error writing failed done.json for workspace "
            f"#{state.workspace_num}: {exc}",
            file=sys.stderr,
        )
    if not os.path.isfile(done_path):
        print(
            f"Error: workspace #{state.workspace_num} still has no "
            f"done.json at {done_path}",
            file=sys.stderr,
        )


def finalize_runner_shutdown(
    *,
    context: RunnerShutdownContext,
    state: RunnerShutdownState,
    deps: RunnerShutdownDeps,
) -> None:
    """Run final cleanup, completion marker, error report, and notification."""
    if state.running_marker_path and os.path.exists(state.running_marker_path):
        try:
            os.unlink(state.running_marker_path)
            deps.update_artifact_index(context.artifacts_dir)
        except OSError:
            pass

    auto_dismiss = bool(os.environ.get("SASE_AGENT_AUTO_DISMISS"))
    workspace_held = False
    hold_done_marker_ensured = False
    killed = deps.was_killed()
    steps_hidden = deps.all_steps_hidden(state.current_artifacts_dir)
    deferred_commits = (
        deferred_commit_details(state.current_artifacts_dir) if state.success else []
    )
    shell_handoff_transferred = (
        state.exec_outcome == MONITOR_OUTCOME
        and monitor_handoff_claim_transferred(
            context.project_file,
            state.workspace_num,
            cl_name=context.cl_name,
        )
    ) or (
        state.exec_outcome == GATE_OUTCOME
        and gate_handoff_claim_moved(
            context.project_file,
            state.workspace_num,
            cl_name=context.cl_name,
        )
    )
    retention_handled = False
    retention_marker_written = False
    workspace_held = False
    if not context.is_home_mode and not shell_handoff_transferred and not killed:
        retention_handled, workspace_held, retention_marker_written = (
            _settle_failed_staged_workspace(
                context=context,
                state=state,
                write_error_done_marker=deps.write_error_done_marker,
            )
        )
    hold_done_marker_ensured = retention_marker_written
    if not context.is_home_mode and not shell_handoff_transferred:
        try:
            if retention_handled:
                if workspace_held:
                    print(
                        f"Workspace #{state.workspace_num} held (stranded staged work)"
                    )
            elif _should_hold_workspace(
                state,
                was_killed=killed,
                auto_dismiss=auto_dismiss,
                steps_hidden=steps_hidden,
                has_deferred_commit=bool(deferred_commits),
            ):
                _ensure_failed_done_marker(
                    context=context,
                    state=state,
                    write_error_done_marker=deps.write_error_done_marker,
                )
                hold_done_marker_ensured = True
                from sase.running_field import hold_workspace_claim

                hold_kwargs: dict[str, Any] = {"caller_tag": "agent-finalize"}
                if state.exec_outcome == "hijacked":
                    hold_kwargs["expected_pid"] = os.getpid()
                result = hold_workspace_claim(
                    context.project_file,
                    state.workspace_num,
                    context.workflow_name,
                    context.cl_name,
                    context.artifacts_timestamp,
                    **hold_kwargs,
                )
                workspace_held = result.success
                if workspace_held:
                    if state.exec_outcome == "hijacked":
                        hold_reason = "hijacked"
                        hold_next = "recover the agent in ace to release it"
                    elif deferred_commits:
                        hold_reason = "deferred commit"
                        hold_next = "dismiss the agent in ace to release it"
                    else:
                        hold_reason = "visible failed run"
                        hold_next = "dismiss the agent in ace to release it"
                    print(
                        f"Workspace #{state.workspace_num} held ({hold_reason}) — "
                        f"{hold_next}"
                    )
                else:
                    print(
                        f"Error holding workspace #{state.workspace_num}: "
                        f"{result.error or 'unknown error'}",
                        file=sys.stderr,
                    )
            else:
                from sase.running_field import release_workspace
                from sase.workspace_provider.occupant import clear_occupant_record

                release_workspace(
                    context.project_file,
                    state.workspace_num,
                    context.workflow_name,
                    context.cl_name,
                    caller_tag="agent-finalize",
                    expected_pid=os.getpid(),
                )
                clear_occupant_record(state.workspace_dir)
                print("Workspace released")
        except Exception as e:
            print(f"Error updating workspace claim: {e}", file=sys.stderr)

    if state.exec_outcome == "hijacked":
        try:
            from sase.agent.hijack.ledger import mark_stopping_if_requested

            mark_stopping_if_requested(
                state.current_artifacts_dir or context.artifacts_dir
            )
        except Exception as e:
            print(f"Error advancing hijack ledger: {e}", file=sys.stderr)

    held_bead_claim = _held_bead_claim_for_shutdown(context, state)
    if held_bead_claim is not None:
        try:
            if (
                not _has_staged_handoff(context.artifacts_dir)
                and not _agent_meta_has_promoted_bead_claim(context.artifacts_dir)
                and state.exec_outcome != "hijacked"
            ):
                from sase.bead.claims import (
                    BeadClaimReleaseOutcome,
                    release_bead_claim_for_agent,
                )

                outcome = release_bead_claim_for_agent(
                    project_name=held_bead_claim.project_name,
                    bead_id=held_bead_claim.bead_id,
                    agent_name=held_bead_claim.agent_name,
                )
                if outcome is not BeadClaimReleaseOutcome.ERROR:
                    clear_bead_claim_marker(context.artifacts_dir)
        except Exception as e:
            print(
                f"Warning: Failed to release waiting bead claim: {e}", file=sys.stderr
            )

    # Flush buffered stdio first so the completion marker appended below
    # stays last in the shared runner output file.
    try:
        sys.stdout.flush()
    except (AttributeError, ValueError, OSError):
        pass
    try:
        sys.stderr.flush()
    except (AttributeError, ValueError, OSError):
        pass
    try:
        with open(context.output_path, "a") as f:
            f.write("\n=== AGENT_RUN_COMPLETE ===\n")
            f.write(f"Status: {'SUCCESS' if state.success else 'FAILED'}\n")
            f.write(f"Duration: {state.duration}\n")
    except Exception as e:
        print(f"Error writing completion marker: {e}", file=sys.stderr)

    if auto_dismiss and state.exec_outcome != "hijacked":
        deps.auto_dismiss_completed_agent(context.cl_name, context.artifacts_timestamp)

    error_report_path: str | None = None
    if not state.success and state.error_summary and state.exec_outcome != "hijacked":
        if not hold_done_marker_ensured:
            _ensure_failed_done_marker(
                context=context,
                state=state,
                write_error_done_marker=deps.write_error_done_marker,
            )
        error_report_path = deps.write_error_report(
            state.current_artifacts_dir,
            agent_model=state.agent_model,
            agent_llm_provider=state.agent_llm_provider,
            workflow_name=context.workflow_name,
            cl_name=context.cl_name,
            duration=state.duration,
            error_summary=state.error_summary,
            error_traceback=state.error_traceback_str,
            submitted_prompt=context.submitted_prompt,
            workspace_dir=state.workspace_dir,
            held_workspace_num=state.workspace_num if workspace_held else None,
            output_path=context.output_path,
            agent_name=state.agent_name,
        )

    if (
        not state.suppress_completion_notification
        and not killed
        and not steps_hidden
        and state.exec_outcome != "hijacked"
    ):
        deps.send_completion_notification(
            cl_name=context.cl_name,
            artifacts_timestamp=context.artifacts_timestamp,
            workflow_name=context.workflow_name,
            success=state.success,
            agent_hidden=state.agent_hidden or state.force_silent_notification,
            agent_name=state.agent_name,
            agent_model=state.agent_model,
            agent_llm_provider=state.agent_llm_provider,
            error_summary=state.error_summary,
            error_report_path=error_report_path,
            saved_path=state.saved_path,
            diff_path=state.diff_path,
            current_artifacts_dir=state.current_artifacts_dir,
            markdown_pdf_paths=state.markdown_pdf_paths,
            markdown_source_count=state.markdown_source_count,
            image_paths=state.image_paths,
            video_paths=state.video_paths,
            output_path=context.output_path,
            step_output=state.step_output,
            prompt=context.prompt,
            outcome=state.exec_outcome,
            runtime=state.runtime,
            held_workspace_num=state.workspace_num if workspace_held else None,
            held_workspace_dir=state.workspace_dir if workspace_held else None,
        )
