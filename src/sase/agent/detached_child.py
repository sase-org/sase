"""Shared out-of-process family spawn primitive.

Two call sites spawn a detached child agent from inside a live process and
move the caller's workspace claim to it: :mod:`sase.monitor.followup`
(launching the agent named by a monitor's ``monitor_next_action`` once the
monitored command settles) and :mod:`sase.axe.run_agent_retry_spawn`
(handing a failing agent's state to a fresh child on retry). Both used to
hand-roll the timestamp reservation, workflow-name derivation, and
``spawn_agent_subprocess`` call; :func:`spawn_detached_child` is that shared
claim-continuity primitive.

:func:`family_attach_env` and :func:`spawn_family_successor` layer the
``%id(<suffix>, family=<parent>)`` family-attach machinery
(:mod:`sase.agent.family_attach`) on top, for the monitor-follow-up spawn.
They import the low-level ``_family_attach_*`` modules directly rather than
the ``sase.agent.family_attach`` facade, because that facade's
``_family_attach_launch`` submodule imports this module for
``family_attach_env`` -- going through the facade here would cycle back.

Explicitly **not** merged here: ``bead/work.py`` builds ``%id(!name,
bead=...)`` prompt directives and launches through ``launch_agents_from_cwd``,
the user-equivalent launch path with its own validation, gating, and
fan-out. Rerouting it through this primitive would bypass launch validation,
not share it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, replace

from sase.agent import _family_attach_resolution as _resolution
from sase.agent import _family_attach_types as _types
from sase.agent.launch_types import AgentLaunchResult
from sase.agent.launch_validation import INTERNAL_AGENT_NAME_BYPASS_ENV
from sase.core.agent_launch_facade import reserve_launch_timestamp_batch

FamilyAttachDirective = _types.FamilyAttachDirective
FamilyAttachLaunchPlan = _types.FamilyAttachLaunchPlan

#: A ``spawn_agent_subprocess``-shaped callable. Callers that expose their own
#: module-level ``spawn_agent_subprocess`` name for tests to monkeypatch
#: (e.g. :mod:`sase.monitor.followup`) forward it in here instead of this
#: module resolving its own import, so the monkeypatch keeps taking effect.
SpawnFn = Callable[..., AgentLaunchResult]

#: A ``resolve_family_attach_plan``-shaped callable, injectable for tests the
#: same way :func:`sase.agent._family_attach_launch.prepare_family_attach_launch`
#: takes its own resolver.
ResolvePlanFn = Callable[..., FamilyAttachLaunchPlan]


def family_attach_env(plan: FamilyAttachLaunchPlan) -> dict[str, str]:
    """Encode ``plan`` into the env vars a family-attach child boot reads."""
    return {
        INTERNAL_AGENT_NAME_BYPASS_ENV: "1",
        _types.FAMILY_ATTACH_ENV: json.dumps(asdict(plan), sort_keys=True),
    }


def spawn_detached_child(
    *,
    project_name: str,
    prompt: str,
    workspace_dir: str,
    workspace_num: int,
    cl_name: str,
    transfer_from_pid: int | None,
    extra_env: dict[str, str] | None = None,
    project_file: str | None = None,
    update_target: str = "",
    history_sort_key: str = "",
    is_home_mode: bool = False,
    vcs_ref: tuple[str, str] | None = None,
    spawn_fn: SpawnFn | None = None,
) -> AgentLaunchResult:
    """Spawn a detached child agent, transferring the caller's workspace claim.

    Reserves a globally unique launch timestamp, derives the
    ``ace(run)-<timestamp>`` workflow name from it, and delegates to
    :func:`sase.agent.launcher.spawn_agent_subprocess` with
    ``retry_transfer_from_pid=transfer_from_pid`` -- the claim-continuity
    call both :mod:`sase.monitor.followup` and
    :mod:`sase.axe.run_agent_retry_spawn` need. ``project_file`` defaults to
    the canonical path for ``project_name`` when the caller does not already
    have one resolved.
    """
    from sase.agent.launcher import spawn_agent_subprocess
    from sase.workflows.utils import get_project_file_path

    spawn = spawn_fn or spawn_agent_subprocess
    timestamp = reserve_launch_timestamp_batch(1)[0]
    return spawn(
        cl_name=cl_name,
        project_file=project_file or get_project_file_path(project_name),
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
        workflow_name=f"ace(run)-{timestamp}",
        prompt=prompt,
        timestamp=timestamp,
        update_target=update_target,
        project_name=project_name,
        history_sort_key=history_sort_key,
        is_home_mode=is_home_mode,
        vcs_ref=vcs_ref,
        extra_env=extra_env,
        retry_transfer_from_pid=transfer_from_pid,
    )


def spawn_family_successor(
    directive: FamilyAttachDirective,
    *,
    project_name: str,
    prompt: str,
    workspace_dir: str,
    workspace_num: int,
    transfer_from_pid: int | None,
    cl_name: str | None = None,
    agent_family_role: str | None = None,
    vcs_ref: tuple[str, str] | None = None,
    spawn_fn: SpawnFn | None = None,
    resolve_plan: ResolvePlanFn | None = None,
) -> AgentLaunchResult:
    """Resolve ``directive`` and spawn the resolved family member.

    Applies the overrides an out-of-process starter must set on its own
    resolved plan (``parent_is_running=False``, the starter's own role, and
    the workspace it is handing off), layers :func:`family_attach_env`, and
    delegates to :func:`spawn_detached_child`. ``vcs_ref`` is the starter's
    VCS workflow type plus ref, forwarded so the child inherits the same
    pre-allocation env the launcher already knows how to emit. The
    subprocess does not report its own name back until it boots, so the
    returned result's ``agent_name`` is always filled in from the resolved
    plan.
    """
    resolve = resolve_plan or _resolution.resolve_family_attach_plan
    plan = resolve(directive, project_name=project_name)
    launch_plan = replace(
        plan,
        parent_is_running=False,
        agent_family_role=agent_family_role or plan.agent_family_role,
        parent_workspace_dir=workspace_dir or plan.parent_workspace_dir,
        parent_workspace_num=workspace_num,
    )
    result = spawn_detached_child(
        project_name=project_name,
        prompt=prompt,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
        cl_name=cl_name or launch_plan.agent_name,
        transfer_from_pid=transfer_from_pid,
        extra_env=family_attach_env(launch_plan),
        vcs_ref=vcs_ref,
        spawn_fn=spawn_fn,
    )
    return replace(result, agent_name=result.agent_name or launch_plan.agent_name)


__all__: list[str] = [
    "FamilyAttachDirective",
    "SpawnFn",
    "family_attach_env",
    "spawn_detached_child",
    "spawn_family_successor",
]
