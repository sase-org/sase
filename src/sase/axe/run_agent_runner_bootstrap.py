"""Pre-wait bootstrap phase for ``run_agent_runner``.

Everything here runs before the runner blocks on dependencies: artifacts
directory resolution, prompt loading, telemetry, xprompt preprocessing, and
directive extraction. It stops at the point where the runner knows what it is
waiting for, so ``run_agent_runner`` can own admission control.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Any

from sase.axe.run_agent_phases import AgentInfo, extract_directives_and_write_meta
from sase.axe.run_agent_retry_spawn import RetryHandoff
from sase.axe.run_agent_runner_cli import read_prompt_file
from sase.axe.run_agent_runner_refresh import RUNNER_CODE_REFRESHED_ENV
from sase.axe.run_agent_runner_setup import (
    apply_retry_chain_to_meta,
    enter_agent_workspace,
    load_retry_handoff_from_env,
    preprocess_prompt_xprompts,
    print_agent_start_banner,
    setup_artifacts_directory,
    write_agent_meta,
    write_submitted_xprompt_artifact,
)
from sase.axe.run_agent_runner_signals import (
    install_workspace_release_sigterm_handler,
)
from sase.axe.run_agent_runner_state import RunnerRunState
from sase.bead.claims import (
    BeadClaimMarker,
    claim_bead_for_waiting_agent,
    retain_in_progress_bead_for_replacement,
    write_bead_claim_marker,
)
from sase.agent.force_reuse_bead import ForceReuseBeadAssociation
from sase.telemetry import init_telemetry, register_flush_on_exit


@dataclass(frozen=True)
class RunnerBootstrap:
    """Directive-derived facts the wait and launch phases both consume."""

    info: AgentInfo
    agent_meta: dict[str, Any]
    retry_handoff: RetryHandoff | None
    deferred_workspace: bool
    # Whether this run blocks on other agents/beads/time before launching.
    has_dependency_wait: bool
    # ``has_dependency_wait`` plus the runner-slot queue admissions.
    has_wait: bool
    force_reuse_bead_association: ForceReuseBeadAssociation | None = None


def _write_bootstrap_agent_meta(
    artifacts_dir: str,
    *,
    output_path: str,
    refreshed: bool,
) -> None:
    """Seed process metadata without erasing a refreshed run's launch identity."""
    agent_meta: dict[str, Any] = {}
    if refreshed:
        meta_path = os.path.join(artifacts_dir, "agent_meta.json")
        try:
            with open(meta_path, encoding="utf-8") as f:
                existing_meta = json.load(f)
            if isinstance(existing_meta, dict):
                agent_meta.update(existing_meta)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass

    agent_meta.update({"pid": os.getpid(), "output_path": output_path})
    write_agent_meta(artifacts_dir, agent_meta)


def _capture_commit_finalizer_baseline(artifacts_dir: str) -> None:
    """Snapshot pre-existing repository checkouts before this agent's first turn.

    A family-attach continuation inherits its parent's baseline instead of
    capturing a fresh one: it runs in the same lane/workspace as its parent,
    so the parent's still-uncommitted work is this run's own responsibility
    to commit, not foreign dirt to exclude (plan
    ``202608/lane_baseline_inheritance.md``).

    Deferred imports avoid a module-load cycle between ``sase.axe`` and
    ``sase.llm_provider``, the same constraint ``_invoke.py`` works around
    with its own lazy ``run_agent_helpers`` imports.
    """
    from sase.llm_provider.commit_finalizer_baseline import capture_dirty_baseline
    from sase.llm_provider.commit_finalizer_config import (
        resolve_finalizer_project_dir,
    )

    if _inherit_parent_commit_finalizer_baseline(artifacts_dir):
        return
    capture_dirty_baseline(resolve_finalizer_project_dir(), artifacts_dir)


def _inherit_parent_commit_finalizer_baseline(artifacts_dir: str) -> bool:
    """Copy a family-attach parent's baseline into ``artifacts_dir``.

    Returns ``True`` when the parent's baseline was inherited, so the caller
    skips capturing a fresh one. Best-effort: any missing plan, missing
    parent baseline file, or copy failure falls back to a fresh capture
    rather than failing the run, matching ``capture_dirty_baseline``'s own
    contract.
    """
    import shutil

    from sase.agent.family_attach import (
        FamilyAttachError,
        load_family_attach_plan_from_env,
    )
    from sase.llm_provider.commit_finalizer_baseline import (
        BASELINE_FILENAME,
        FINALIZER_BASELINE_FILENAME,
    )

    try:
        plan = load_family_attach_plan_from_env()
    except FamilyAttachError:
        return False
    if plan is None:
        return False

    parent_generic = os.path.join(
        plan.parent_artifacts_dir, FINALIZER_BASELINE_FILENAME
    )
    parent_legacy = os.path.join(plan.parent_artifacts_dir, BASELINE_FILENAME)
    if os.path.isfile(parent_generic):
        source = parent_generic
    elif os.path.isfile(parent_legacy):
        source = parent_legacy
    else:
        return False

    try:
        os.makedirs(artifacts_dir, exist_ok=True)
        shutil.copyfile(
            source,
            os.path.join(artifacts_dir, os.path.basename(source)),
        )
    except OSError:
        return False
    return True


def _load_submitted_prompt(state: RunnerRunState) -> None:
    """Read the one-shot prompt file and persist the launch-boundary artifact."""
    refreshed_prompt_fallback: str | None = None
    if RUNNER_CODE_REFRESHED_ENV in os.environ:
        refreshed_prompt_fallback = os.path.join(
            state.artifacts_dir,
            "submitted_xprompt.md",
        )
    state.prompt = read_prompt_file(
        state.prompt_file,
        refreshed_fallback_file=refreshed_prompt_fallback,
    )
    state.submitted_xprompt = state.prompt
    try:
        write_submitted_xprompt_artifact(state.artifacts_dir, state.submitted_xprompt)
    except OSError as e:
        print(f"Warning: Failed to write submitted_xprompt.md: {e}", file=sys.stderr)


def _wait_flags(info: AgentInfo) -> tuple[bool, bool]:
    """Return ``(has_dependency_wait, has_wait)`` for extracted directives."""
    has_dependency_wait = (
        bool(info.wait_names)
        or bool(info.wait_identity_deps)
        or bool(info.wait_fork_sources)
        or bool(info.wait_beads)
        or info.wait_duration is not None
        or info.wait_until is not None
    )
    has_wait = (
        has_dependency_wait
        or info.wait_runners is not None
        or info.wait_priority is not None
    )
    return has_dependency_wait, has_wait


def _force_reuse_bead_association_for_run(
    *,
    agent_name: str | None,
    bead_id: str | None,
) -> ForceReuseBeadAssociation | None:
    """Consume the one-shot replacement marker if it matches this run."""
    from sase.agent.force_reuse_bead import consume_force_reuse_bead_association
    from sase.bead.force_reuse import same_current_owner_agent_name

    association = consume_force_reuse_bead_association(os.environ)
    if association is None or agent_name is None or bead_id is None:
        return None
    if association.bead_id != bead_id:
        return None
    if not same_current_owner_agent_name(association.owner_name, agent_name):
        return None
    return association


def _claim_bead_before_wait(
    state: RunnerRunState,
    info: AgentInfo,
    *,
    force_reuse_bead_association: ForceReuseBeadAssociation | None,
) -> None:
    """Hold this run's bead across the wait so a peer cannot take it."""
    if info.bead_id is None or state.agent_name is None or not state.project_name:
        return
    if (
        force_reuse_bead_association is not None
        and retain_in_progress_bead_for_replacement(
            project_name=state.project_name,
            bead_id=info.bead_id,
            agent_name=state.agent_name,
            prior_owner=force_reuse_bead_association.owner_name,
        )
    ):
        return
    if not claim_bead_for_waiting_agent(
        project_name=state.project_name,
        bead_id=info.bead_id,
        agent_name=state.agent_name,
    ):
        return
    state.held_bead_claim = BeadClaimMarker(
        bead_id=info.bead_id,
        agent_name=state.agent_name,
        project_name=state.project_name,
    )
    write_bead_claim_marker(
        state.artifacts_dir,
        project_name=state.project_name,
        bead_id=info.bead_id,
        agent_name=state.agent_name,
    )


def bootstrap_agent_run(state: RunnerRunState) -> RunnerBootstrap:
    """Resolve artifacts, prompt, and directives before any dependency wait."""
    install_workspace_release_sigterm_handler(
        project_file=state.project_file,
        workspace_num=state.workspace_num,
        workspace_dir=state.workspace_dir,
        workflow_name=state.workflow_name,
        cl_name=state.cl_name,
        is_home_mode=state.is_home_mode,
        artifacts_dir_getter=lambda: state.signal_fallback_artifacts_dir,
    )

    project_name, artifacts_timestamp, artifacts_dir = setup_artifacts_directory(
        timestamp=state.timestamp,
        project_file=state.project_file,
        cl_name=state.cl_name,
        is_home_mode=state.is_home_mode,
    )
    state.project_name = project_name
    state.artifacts_timestamp = artifacts_timestamp
    state.rebind_artifacts_dir(artifacts_dir)

    # Persist the raw output location before any prompt processing or
    # dependency wait. A refreshed pass reuses the artifact directory, so retain
    # its durable launch metadata until directive extraction can carry it into
    # the rebuilt record.
    _write_bootstrap_agent_meta(
        artifacts_dir,
        output_path=state.output_path,
        refreshed=RUNNER_CODE_REFRESHED_ENV in os.environ,
    )

    _load_submitted_prompt(state)

    init_telemetry()
    register_flush_on_exit(
        job="agent_runner", workflow=state.workflow_name, instance=state.timestamp
    )

    if RUNNER_CODE_REFRESHED_ENV not in os.environ:
        print_agent_start_banner(
            cl_name=state.cl_name,
            workspace_dir=state.workspace_dir,
            workflow_name=state.workflow_name,
            prompt=state.prompt,
        )

    # The preprocessed VCS tag is superseded by agent-ref resolution in the
    # launch phase, so only the rewritten prompts are carried forward.
    state.prompt, _, raw_resolved_prompt = preprocess_prompt_xprompts(
        state.prompt, state.artifacts_dir
    )
    retry_handoff = load_retry_handoff_from_env()
    deferred_workspace = bool(os.environ.get("SASE_AGENT_DEFERRED_WORKSPACE"))

    enter_agent_workspace(state.workspace_dir, state.workspace_num)
    _capture_commit_finalizer_baseline(state.artifacts_dir)

    info = extract_directives_and_write_meta(
        state.prompt,
        state.workspace_dir,
        state.artifacts_dir,
        cl_name=state.cl_name,
        workspace_num=state.workspace_num,
        output_path=state.output_path,
        raw_resolved_prompt=raw_resolved_prompt,
    )
    state.agent_name = info.name
    state.agent_model = info.model
    state.agent_llm_provider = info.llm_provider
    state.agent_vcs_provider = info.vcs_provider
    state.agent_hidden = info.hidden
    force_reuse_bead_association = _force_reuse_bead_association_for_run(
        agent_name=state.agent_name,
        bead_id=info.bead_id,
    )

    agent_meta = apply_retry_chain_to_meta(
        retry_handoff=retry_handoff,
        agent_meta={**info.meta, "output_path": state.output_path},
        artifacts_dir=state.artifacts_dir,
    )

    has_dependency_wait, has_wait = _wait_flags(info)
    # Launch preflight is conservative: a deferred launch can still reach this
    # point with no extracted wait metadata after preprocessing or compatibility
    # normalization drops a no-op wait. That is a legitimate state, not a bug:
    # the run below skips dependency waiting, proceeds through runner-slot
    # admission, and the launch phase's `_prepare_workspace_and_repos()` claims
    # a real workspace before `launch_agent_run()` ever executes the model. Do
    # not resurrect the old fatal assertion here.
    if has_wait:
        _claim_bead_before_wait(
            state,
            info,
            force_reuse_bead_association=force_reuse_bead_association,
        )

    return RunnerBootstrap(
        info=info,
        agent_meta=agent_meta,
        retry_handoff=retry_handoff,
        deferred_workspace=deferred_workspace,
        has_dependency_wait=has_dependency_wait,
        has_wait=has_wait,
        force_reuse_bead_association=force_reuse_bead_association,
    )
