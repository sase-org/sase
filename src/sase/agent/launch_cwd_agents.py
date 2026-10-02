"""Generic CWD-based launch flow for background agents."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from sase.agent.launch_cwd_common import LaunchHistoryRecorder
from sase.agent.launch_cwd_fanout import (
    launch_alt_branch_if_applicable,
    launch_multi_prompt_branch,
    launch_repeat_branch_if_applicable,
)
from sase.agent.launch_cwd_guards import (
    guard_hard_disabled_launch_units,
    guard_project_tags_for_launch_units,
    guard_typed_directives_require_admission,
)
from sase.agent.launch_cwd_segments import expand_launch_segments
from sase.agent.launch_cwd_single import launch_single_agent
from sase.agent.launch_types import AgentLaunchResult
from sase.core.paths import sase_projects_dir

if TYPE_CHECKING:
    from sase.agent.launch_guard import LaunchUnitInput
    from sase.history.prompt_store import PromptOrigin


def launch_agents_from_cwd_impl(
    query: str,
    extra_env: dict[str, str] | None = None,
    segment_extra_env: Sequence[dict[str, str] | None] | None = None,
    timestamp: str | None = None,
    *,
    recursive_launch_agents_from_cwd: Callable[..., list[AgentLaunchResult]]
    | None = None,
    launch_units: Sequence[LaunchUnitInput] | None = None,
    origin: PromptOrigin | None = None,
    history_text: str | None = None,
) -> list[AgentLaunchResult]:
    """Resolve project context from CWD and launch one or more background agents.

    This is the high-level entry point used by mobile launch surfaces that need
    every slot from multi-prompt, multi-model, alt, and repeat fan-out.

    For multi-prompt queries (containing ``---`` separators), all segments
    are launched sequentially.

    Args:
        query: The prompt/xprompt string to run as an agent.
        timestamp: Optional preallocated launch timestamp for fan-out callers.
        launch_units: Optional ACE-resolved expanded units. When supplied,
            these replace ``parse_multi_prompt`` + xprompt-swarm expansion.
        history_text: Optional ingress-owned canonical text the human
            submitted. When given, history records it instead of *query*,
            so swarm/force-reuse rewrites record what was submitted.

    Returns:
        AgentLaunchResult records for every spawned slot.

    Raises:
        RuntimeError: If workspace allocation or claiming fails.
        DisabledProviderLaunchError: If a unit can only run on a hard-disabled
            provider. Unexpected guard failures are logged and swallowed.
    """

    from sase.history.prompt_store_mutations import effective_prompt_origin

    # Provenance resolves once here and the history writers gate on it, so a
    # machine-originated launch writes no row on success or on failure alike.
    effective_origin: PromptOrigin | None = effective_prompt_origin(
        origin, launch_envs=(extra_env, *(segment_extra_env or ()))
    )

    from sase.agent.names import ensure_historical_auto_name_migration
    from sase.project_aliases import canonicalize_project_aliases_in_prompt

    ensure_historical_auto_name_migration()
    # The recorded text resolves once here: an explicit ingress-owned text
    # wins, otherwise the submitted query. Either is canonicalized like the
    # query so dedup and the `project:` filter keep working.
    recorded_text: str | None
    if history_text:
        try:
            recorded_text = canonicalize_project_aliases_in_prompt(history_text)
        except Exception:
            recorded_text = history_text
    else:
        recorded_text = None

    def record_pre_expansion_failure(text: str) -> None:
        from sase.history.prompt import (
            record_failed_launch_prompt as record_interactive_failed_launch,
        )

        record_interactive_failed_launch(
            recorded_text if recorded_text is not None else text,
            origin=effective_origin,
        )

    if "+" in query:
        # Validate tags against the raw prompt before canonicalization
        # expands resolved tags into `#<workflow>:<key>` refs (which would
        # hide disabled/no-provider targets from the policy check). Alt
        # branches and `---` segments are validated as future units; the
        # post-fan-out unit guard below re-checks anchored leftovers.
        try:
            from sase.project_tags import (
                ProjectTagError as _ProjectTagError,
                validate_project_tags_for_launch as _validate_tags,
            )

            _validate_tags(query)
        except _ProjectTagError:
            record_pre_expansion_failure(query)
            raise
        except Exception:  # noqa: BLE001 - cold catalog fails open here.
            pass
    try:
        query = canonicalize_project_aliases_in_prompt(query)
    except Exception:
        # An alias-map conflict here escapes before the validation/spawn
        # branches below can record the failure; preserve the original
        # submitted query so it stays recoverable from the stash.
        record_pre_expansion_failure(query)
        raise
    submitted_query = query
    if recorded_text is None:
        recorded_text = submitted_query
    # Lineage inheritance (R2): agent-initiated direct launches stamp the
    # inherited tab here. Idempotent with the LaunchApproval stamping, which
    # runs first when approval gates the launch.
    from sase.xprompt.directive_edit import (
        apply_inherited_agent_tab as _apply_inherited_tab,
        inherited_agent_tab as _inherited_tab,
    )

    query = _apply_inherited_tab(query, _inherited_tab())

    from sase.main.utils import ensure_project_file_and_get_workspace_num

    # --- Resolve project context ---
    # Read-only lookup: a plain launch from a git checkout must not register
    # that checkout as a SASE project. Explicit VCS/known-project refs resolved
    # below still activate their real project, and bare prompts fall back to
    # home mode rather than bootstrapping a CWD ProjectSpec.
    project_file, workspace_num, project_name = (
        ensure_project_file_and_get_workspace_num(create_missing=False)
    )

    is_home_mode = project_file is None
    if is_home_mode:
        from sase.ace.patch.project_spec_path import preferred_project_spec_path

        project_name = "home"
        home_dir = str(sase_projects_dir() / "home")
        project_file = preferred_project_spec_path(home_dir, "home")

    assert project_file is not None
    assert project_name is not None

    # --- Multi-prompt detection and xprompt-swarm expansion ---
    expanded = expand_launch_segments(
        query,
        launch_units=launch_units,
        segment_extra_env=segment_extra_env,
    )

    # One recorder per launch: every guard and branch records the resolved
    # submitted text, so fan-out records the invocation once instead of each
    # slot's rewritten text. A bare swarm trigger is short, so fan-out
    # through `---` segments, swarm expansion, or ACE units keeps the
    # short-text allowance the multi-prompt branch uses today; other launches
    # keep the five-word threshold.
    from sase.agent.multi_prompt import is_multi_prompt as _is_multi_prompt

    recorder = LaunchHistoryRecorder(
        text=recorded_text,
        origin=effective_origin,
        allow_short=(
            len(expanded.segments) > 1
            or launch_units is not None
            or any(expanded.swarm_xprompts)
            or _is_multi_prompt(recorded_text)
        ),
    )

    guard_hard_disabled_launch_units(
        submitted_query,
        expanded_segments=expanded.segments,
        template_groups=expanded.template_groups,
        swarm_xprompts=expanded.swarm_xprompts,
        recorder=recorder,
    )
    guard_project_tags_for_launch_units(
        expanded_segments=expanded.segments,
        recorder=recorder,
    )
    if not (extra_env or {}).get("SASE_LAUNCH_DISPATCH_FINGERPRINT"):
        guard_typed_directives_require_admission(
            submitted_query,
            expanded.segments,
            recorder=recorder,
        )

    from sase.agent.agent_name_keys import resolve_agent_name_key_markers

    expanded_segments = resolve_agent_name_key_markers(expanded.segments)

    if not expanded_segments:
        return []

    if len(expanded_segments) > 1:
        return launch_multi_prompt_branch(
            expanded_segments,
            expanded.local_xprompts,
            project_file=project_file,
            project_name=project_name,
            is_home_mode=is_home_mode,
            extra_env=extra_env,
            segment_extra_env=expanded.segment_extra_env,
            segment_template_groups=expanded.template_groups,
            segment_swarm_xprompts=expanded.swarm_xprompts,
            submitted_query=submitted_query,
            recorder=recorder,
        )

    from sase.agent.launch_projects import (
        enable_known_project_vcs_refs_for_launch_prompt,
    )
    from sase.xprompt._parsing import normalize_default_vcs_workflow

    query = normalize_default_vcs_workflow(expanded_segments[0])
    enable_known_project_vcs_refs_for_launch_prompt(query)
    if expanded.segment_extra_env:
        segment_env = expanded.segment_extra_env[0] or {}
        extra_env = {**(extra_env or {}), **segment_env}
    if expanded.swarm_xprompts[0]:
        from sase.xprompt.used_xprompts import launch_swarm_env_entries

        extra_env = {
            **(extra_env or {}),
            **launch_swarm_env_entries(expanded.swarm_xprompts[0]),
        }

    # --- Repeat fan-out ---
    # When %r:N is present, spawn N independent agents before any further
    # dispatch.  Each spec's prompt has %r / %i stripped and %i:<base>.<k>
    # re-injected, so the recursive call resolves through the single-agent
    # path without re-triggering this branch.
    repeat_results = launch_repeat_branch_if_applicable(
        query,
        extra_env=extra_env,
        recursive_launch=(
            recursive_launch_agents_from_cwd or launch_agents_from_cwd_impl
        ),
        recorder=recorder,
    )
    if repeat_results is not None:
        return repeat_results

    # --- Alt-split detection ---
    alt_results = launch_alt_branch_if_applicable(
        query,
        local_xprompts=expanded.local_xprompts,
        project_file=project_file,
        project_name=project_name,
        is_home_mode=is_home_mode,
        extra_env=extra_env,
        recorder=recorder,
    )
    if alt_results is not None:
        return alt_results

    return launch_single_agent(
        query,
        project_file=project_file,
        project_name=project_name,
        is_home_mode=is_home_mode,
        workspace_num=workspace_num,
        extra_env=extra_env,
        timestamp=timestamp,
        recorder=recorder,
    )
