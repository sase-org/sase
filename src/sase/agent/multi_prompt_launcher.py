"""Multi-prompt sequential launch orchestration.

When a prompt splits into multiple segments (via ``---`` separators),
launch each segment as a separate agent. Bare ``%wait`` in segment N+1 is
rewritten to the planned name of agent N when that name is knowable; otherwise
the launcher falls back to the legacy naming poll.
"""

import json
import os
import re
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass

from sase.agent.launcher import AgentLaunchResult
from sase.core.agent_launch_facade import LaunchTimestampBatchAllocator
from sase.xprompt.models import XPrompt

_PLANNED_AGENT_NAME_ENV = "SASE_AGENT_PLANNED_NAME"


class MultiPromptPartialLaunchError(RuntimeError):
    """Raised when one segment of a multi-prompt launch fails after others succeeded.

    ``results`` holds the agents that were spawned before the failure, so
    callers can roll back (e.g. terminate the leaked PIDs).
    """

    def __init__(self, results: list[AgentLaunchResult], cause: BaseException) -> None:
        super().__init__(f"partial multi-prompt launch failed: {cause}")
        self.results = results


def _extract_called_xprompt_names(text: str, available_xprompts: set[str]) -> set[str]:
    """Extract xprompt names called in *text*.

    Supports shorthand syntaxes by preprocessing before extraction.
    """
    from sase.xprompt._parsing import preprocess_shorthand_syntax
    from sase.xprompt.workflow_validator_extract import extract_xprompt_calls

    preprocessed = preprocess_shorthand_syntax(text, available_xprompts)
    return {
        call.name
        for call in extract_xprompt_calls(preprocessed)
        if call.name in available_xprompts
    }


def _local_xprompts_for_segment(
    segment: str, local_xprompts: dict[str, XPrompt]
) -> dict[str, XPrompt]:
    """Return only local xprompts referenced by this segment.

    Includes transitive references between local xprompts so a called xprompt
    can depend on other local xprompts.
    """
    if not local_xprompts:
        return {}

    available = set(local_xprompts.keys())
    needed = _extract_called_xprompt_names(segment, available)
    queue = list(needed)

    while queue:
        name = queue.pop()
        xp = local_xprompts.get(name)
        if xp is None:
            continue
        for called in _extract_called_xprompt_names(xp.content, available):
            if called not in needed:
                needed.add(called)
                queue.append(called)

    # Preserve original definition order for deterministic serialization.
    return {name: xp for name, xp in local_xprompts.items() if name in needed}


def _serialize_local_xprompts(xprompts: dict[str, XPrompt]) -> str:
    """Serialize local xprompts to a temp JSON file.

    Returns the path to the temp file.
    """
    from sase.core.paths import get_sase_tmpdir

    data: dict[str, object] = {}
    for name, xp in xprompts.items():
        data[name] = {
            "name": xp.name,
            "content": xp.content,
            "inputs": [
                {
                    "name": inp.name,
                    "type": inp.type.value,
                    "default": None if inp.default is _UNSET else inp.default,
                    "is_step_input": inp.is_step_input,
                }
                for inp in xp.inputs
            ],
            "source_path": xp.source_path,
            "tags": [t.value for t in xp.tags],
        }

    fd, path = tempfile.mkstemp(
        suffix=".json", prefix="sase_local_xprompts_", dir=get_sase_tmpdir()
    )
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


def deserialize_local_xprompts(path: str) -> dict[str, XPrompt]:
    """Read a local-xprompts JSON file and reconstruct XPrompt objects."""
    from sase.xprompt.models import InputArg, InputType
    from sase.xprompt.tags import parse_tags

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    result: dict[str, XPrompt] = {}
    for name, entry in data.items():
        inputs = []
        for inp in entry.get("inputs", []):
            default = inp.get("default")
            if default is None:
                default = _UNSET
            inputs.append(
                InputArg(
                    name=inp["name"],
                    type=InputType(inp.get("type", "line")),
                    default=default,
                    is_step_input=inp.get("is_step_input", False),
                )
            )
        result[name] = XPrompt(
            name=entry["name"],
            content=entry["content"],
            inputs=inputs,
            source_path=entry.get("source_path"),
            tags=parse_tags(entry.get("tags")),
        )
    return result


def _wait_for_agent_naming(artifacts_dir: str, timeout: float = 30) -> str | None:
    """Poll ``agent_meta.json`` for a ``name`` field.

    Returns the agent name when found, or ``None`` on timeout.
    """
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        try:
            with open(meta_path) as f:
                data = json.load(f)
            if data.get("name"):
                return data["name"]
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        time.sleep(0.5)
    return None


def _extract_static_name_directive(prompt: str) -> str | None:
    """Return an explicit top-level ``%name`` value that is safe to reuse."""
    if "%" not in prompt:
        return None

    from sase.xprompt._directive_types import _DIRECTIVE_ALIASES, _DIRECTIVE_PATTERN
    from sase.xprompt._disabled_regions import protect_disabled_regions
    from sase.xprompt._fenced_blocks import protect_fenced_blocks
    from sase.xprompt._parsing import find_matching_paren_for_args, parse_args

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        raw_name = match.group(1)
        if _DIRECTIVE_ALIASES.get(raw_name, raw_name) != "name":
            continue

        value = ""
        if match.group(2) is not None:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(protected, paren_start)
            if paren_end is not None:
                inner = protected[paren_start + 1 : paren_end]
                positional_args, _ = parse_args(inner)
                value = positional_args[0] if positional_args else ""
        elif match.group(3) is not None:
            colon_arg = match.group(3)
            value = (
                colon_arg[1:-1]
                if colon_arg.startswith("`") and colon_arg.endswith("`")
                else colon_arg
            )

        if not value or "#" in value:
            return None
        return value
    return None


def _has_bare_wait_directive(prompt: str) -> bool:
    """Return True when *prompt* contains a top-level bare ``%wait``."""
    if "%" not in prompt:
        return False

    from sase.xprompt._directive_types import _DIRECTIVE_ALIASES, _DIRECTIVE_PATTERN
    from sase.xprompt._disabled_regions import protect_disabled_regions
    from sase.xprompt._fenced_blocks import protect_fenced_blocks
    from sase.xprompt._parsing import find_matching_paren_for_args

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        raw_name = match.group(1)
        if _DIRECTIVE_ALIASES.get(raw_name, raw_name) != "wait":
            continue
        if match.group(2) is not None:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(protected, paren_start)
            if paren_end is not None and protected[paren_start + 1 : paren_end]:
                continue
        elif match.group(3) is not None or match.group(4) is not None:
            continue
        return True
    return False


def _rewrite_bare_wait_directives(prompt: str, agent_name: str) -> str:
    """Rewrite top-level bare ``%wait``/``%w`` directives to *agent_name*."""
    if "%" not in prompt:
        return prompt

    from sase.xprompt._directive_types import _DIRECTIVE_ALIASES, _DIRECTIVE_PATTERN
    from sase.xprompt._disabled_regions import (
        protect_disabled_regions,
        unprotect_disabled_regions,
    )
    from sase.xprompt._fenced_blocks import (
        protect_fenced_blocks,
        unprotect_fenced_blocks,
    )
    from sase.xprompt._parsing import find_matching_paren_for_args

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    replacements: list[tuple[int, int, str]] = []
    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        raw_name = match.group(1)
        if _DIRECTIVE_ALIASES.get(raw_name, raw_name) != "wait":
            continue
        if match.group(2) is not None:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(protected, paren_start)
            if paren_end is not None and protected[paren_start + 1 : paren_end]:
                continue
            end = paren_end + 1 if paren_end is not None else match.end()
        elif match.group(3) is not None or match.group(4) is not None:
            continue
        else:
            end = match.end()
        replacements.append((match.start(), end, f"%{raw_name}:{agent_name}"))

    rewritten = protected
    for start, end, value in reversed(replacements):
        rewritten = rewritten[:start] + value + rewritten[end:]
    rewritten = unprotect_disabled_regions(rewritten, disabled)
    return unprotect_fenced_blocks(rewritten, fenced)


class _PlannedNameAllocator:
    """Allocate parent-side names for multi-prompt wait rewrites."""

    def __init__(self) -> None:
        self._auto_reserved: set[str] | None = None

    def planned_name_for_prompt(self, prompt: str) -> tuple[str | None, str | None]:
        """Return ``(name, env_value)`` for a prompt, if safely knowable."""
        explicit_name = _extract_static_name_directive(prompt)
        if explicit_name is not None:
            return explicit_name, None

        if "#" in prompt:
            return None, None

        from sase.agent.names import allocate_auto_names

        if self._auto_reserved is None:
            from sase.agent.names import get_active_agent_names

            self._auto_reserved = get_active_agent_names()
        name = allocate_auto_names(1, reserved=self._auto_reserved)[0]
        return name, name


@dataclass(frozen=True)
class _SegmentVcsContext:
    cl_name: str
    project_file: str
    project_name: str
    is_home_mode: bool
    vcs_ref: tuple[str, str] | None
    history_sort_key: str
    update_target: str
    workspace_num: int | None = None
    workspace_dir: str | None = None


def _extract_vcs_ref(prompt: str) -> tuple[str, str] | None:
    """Return the first VCS ref present in *prompt*, if any."""
    from sase.workspace_provider import get_ref_patterns

    for wf_name, pattern in get_ref_patterns().items():
        match = pattern.search(prompt)
        if match is None:
            continue
        ref_value = match.group(1) or match.group(2)
        if ref_value:
            return wf_name, ref_value
    return None


def _resolve_segment_vcs_context(
    *,
    prompt: str,
    fallback_cl_name: str,
    fallback_project_file: str,
    fallback_project_name: str,
    fallback_is_home_mode: bool,
    fallback_vcs_ref: tuple[str, str] | None,
    has_wait: bool,
) -> _SegmentVcsContext:
    """Resolve launch metadata for one multi-prompt segment.

    Multi-prompts can mix VCS refs across segments.  The launcher therefore
    derives the display CL, workspace/project context, pre-allocation ref, and
    history key from the segment's own VCS ref when present, falling back to the
    caller's context for legacy prompts that rely on an already-selected CL.
    """
    from sase.ace.tui.actions.agent_workflow._ref_resolution import (
        is_non_workspace_workflow,
        resolve_ref_from_prompt,
    )

    segment_vcs_ref = _extract_vcs_ref(prompt) or fallback_vcs_ref
    if segment_vcs_ref is None:
        return _SegmentVcsContext(
            cl_name=fallback_cl_name,
            project_file=fallback_project_file,
            project_name=fallback_project_name,
            is_home_mode=fallback_is_home_mode,
            vcs_ref=None,
            history_sort_key="",
            update_target="",
        )

    wf_name, ref_value = segment_vcs_ref
    if is_non_workspace_workflow(wf_name):
        update_target = ""
    else:
        from sase.vcs_provider import VCS_DEFAULT_REVISION

        update_target = VCS_DEFAULT_REVISION
    resolved = resolve_ref_from_prompt(prompt, wf_name, skip_workspace=has_wait)
    if resolved is None:
        return _SegmentVcsContext(
            cl_name=ref_value,
            project_file=fallback_project_file,
            project_name=fallback_project_name,
            is_home_mode=fallback_is_home_mode,
            vcs_ref=segment_vcs_ref,
            history_sort_key=ref_value,
            update_target=update_target,
        )

    project_file, project_name, workspace_dir, workspace_num, resolved_ref = resolved
    return _SegmentVcsContext(
        cl_name=resolved_ref,
        project_file=project_file,
        project_name=project_name,
        is_home_mode=is_non_workspace_workflow(wf_name),
        vcs_ref=(wf_name, resolved_ref),
        history_sort_key=resolved_ref,
        update_target=update_target,
        workspace_num=workspace_num,
        workspace_dir=workspace_dir,
    )


def launch_multi_prompt_agents(
    *,
    segments: list[str],
    local_xprompts: dict[str, XPrompt],
    cl_name: str,
    project_file: str,
    project_name: str,
    is_home_mode: bool,
    vcs_ref: tuple[str, str] | None,
    on_agent_spawned: Callable[[], None] | None = None,
    extra_env: dict[str, str] | None = None,
    default_bare_segments_to_home: bool = False,
) -> list[AgentLaunchResult]:
    """Launch each segment as a separate agent.

    For each segment:
    1. Serialize only segment-referenced local xprompts (if any) to a temp JSON file.
    2. Allocate a workspace and timestamp.
    3. Spawn the agent subprocess.
    4. Poll for the predecessor name only when a following bare ``%wait`` cannot
       be rewritten from the launch plan.

    Returns a list of ``AgentLaunchResult`` for all launched agents.

    On partial failure (one segment raises after others succeeded), raises
    :class:`MultiPromptPartialLaunchError` with the already-spawned results
    so callers can roll back.
    """
    results: list[AgentLaunchResult] = []
    timestamp_allocator = LaunchTimestampBatchAllocator()

    try:
        _spawn_segments_into(
            segments=segments,
            local_xprompts=local_xprompts,
            cl_name=cl_name,
            project_file=project_file,
            project_name=project_name,
            is_home_mode=is_home_mode,
            vcs_ref=vcs_ref,
            on_agent_spawned=on_agent_spawned,
            extra_env=extra_env,
            default_bare_segments_to_home=default_bare_segments_to_home,
            timestamp_allocator=timestamp_allocator,
            results=results,
        )
    except Exception as exc:
        if results:
            raise MultiPromptPartialLaunchError(results, exc) from exc
        raise
    return results


def _spawn_segments_into(
    *,
    segments: list[str],
    local_xprompts: dict[str, XPrompt],
    cl_name: str,
    project_file: str,
    project_name: str,
    is_home_mode: bool,
    vcs_ref: tuple[str, str] | None,
    on_agent_spawned: Callable[[], None] | None,
    extra_env: dict[str, str] | None,
    default_bare_segments_to_home: bool,
    timestamp_allocator: LaunchTimestampBatchAllocator,
    results: list[AgentLaunchResult],
) -> None:
    from sase.agent.launch_timing import LaunchTimingRecorder
    from sase.agent.launcher import spawn_agent_subprocess
    from sase.running_field import (
        get_first_available_axe_workspace,
        get_workspace_directory,
        get_workspace_directory_for_num,
    )
    from sase.artifacts import create_artifacts_directory
    from sase.xprompt.directives import has_wait_directive, split_prompt_for_models
    from sase.xprompt._parsing import normalize_default_vcs_workflow_segment

    timer = LaunchTimingRecorder(
        "agent_launch_multi_prompt",
        {
            "segment_count": len(segments),
            "project_name": project_name,
            "home_mode": is_home_mode,
        },
    )
    name_allocator = _PlannedNameAllocator()
    previous_agent_name: str | None = None
    for i, segment in enumerate(segments):
        if default_bare_segments_to_home:
            with timer.stage("prompt_normalize", segment_index=i):
                segment = normalize_default_vcs_workflow_segment(segment)
        with timer.stage("wait_rewrite", segment_index=i):
            segment_has_bare_wait = _has_bare_wait_directive(segment)
            if segment_has_bare_wait and previous_agent_name:
                segment = _rewrite_bare_wait_directives(segment, previous_agent_name)
                segment_has_bare_wait = False
        with timer.stage("prompt_parse", segment_index=i):
            has_wait = has_wait_directive(segment)
            segment_local_xprompts = _local_xprompts_for_segment(
                segment, local_xprompts
            )
        next_segment_needs_name = i < len(segments) - 1 and _has_bare_wait_directive(
            segments[i + 1]
        )

        # Check for multi-model directive (e.g., %m(opus,sonnet)).
        # Try the raw segment first; if no match and the segment contains
        # xprompt references, expand them and re-check (a referenced xprompt
        # may inject a multi-model directive).
        with timer.stage("fanout_plan", segment_index=i, fanout_kind="model"):
            model_prompts = split_prompt_for_models(
                segment,
                extra_xprompts=segment_local_xprompts or None,
            )
        if model_prompts is None and "#" in segment:
            from sase.xprompt.processor import process_xprompt_references

            with timer.stage("xprompt_expand", segment_index=i):
                expanded = process_xprompt_references(
                    segment,
                    extra_xprompts=segment_local_xprompts or None,
                )
                model_prompts = split_prompt_for_models(
                    expanded,
                    extra_xprompts=segment_local_xprompts or None,
                )

        sub_prompts = model_prompts if model_prompts is not None else [segment]
        with timer.stage(
            "timestamp_allocate_batch",
            segment_index=i,
            slot_count=len(sub_prompts),
        ):
            timestamps = timestamp_allocator.allocate(len(sub_prompts))

        last_timestamp: str | None = None
        last_project_name: str | None = None
        last_planned_name: str | None = None
        for j, sub_prompt in enumerate(sub_prompts):
            with timer.stage("timestamp_allocate", segment_index=i, slot_index=j):
                timestamp = timestamps[j]
                last_timestamp = timestamp
                workflow_name = f"ace(run)-{timestamp}"
            with timer.stage("name_plan", segment_index=i, slot_index=j):
                if next_segment_needs_name:
                    planned_name, planned_env_name = (
                        name_allocator.planned_name_for_prompt(sub_prompt)
                    )
                else:
                    planned_name, planned_env_name = None, None
                last_planned_name = planned_name

            # Each sub-prompt gets its own copy of the local xprompts file
            # (the agent runner deletes it after reading).
            with timer.stage("local_xprompts_serialize", segment_index=i, slot_index=j):
                local_xprompts_file = (
                    _serialize_local_xprompts(segment_local_xprompts)
                    if segment_local_xprompts
                    else None
                )

            with timer.stage("vcs_resolution", segment_index=i, slot_index=j):
                segment_ctx = _resolve_segment_vcs_context(
                    prompt=sub_prompt,
                    fallback_cl_name=cl_name,
                    fallback_project_file=project_file,
                    fallback_project_name=project_name,
                    fallback_is_home_mode=is_home_mode,
                    fallback_vcs_ref=vcs_ref,
                    has_wait=has_wait,
                )

            # Allocate workspace for this sub-prompt.
            with timer.stage("workspace_allocation", segment_index=i, slot_index=j):
                if segment_ctx.workspace_dir is not None:
                    workspace_dir = segment_ctx.workspace_dir
                    assert segment_ctx.workspace_num is not None
                    workspace_num = segment_ctx.workspace_num
                elif segment_ctx.is_home_mode:
                    workspace_dir = os.path.expanduser("~")
                    workspace_num = 0
                elif has_wait:
                    workspace_num = 0
                    workspace_dir = get_workspace_directory(segment_ctx.project_name, 1)
                else:
                    workspace_num = get_first_available_axe_workspace(
                        segment_ctx.project_file
                    )
                    workspace_dir, _ = get_workspace_directory_for_num(
                        workspace_num, segment_ctx.project_name
                    )

            with timer.stage("low_level_spawn", segment_index=i, slot_index=j):
                slot_extra_env = dict(extra_env or {})
                if planned_env_name is not None:
                    slot_extra_env[_PLANNED_AGENT_NAME_ENV] = planned_env_name
                result = spawn_agent_subprocess(
                    cl_name=segment_ctx.cl_name,
                    project_file=segment_ctx.project_file,
                    workspace_dir=workspace_dir,
                    workspace_num=workspace_num,
                    workflow_name=workflow_name,
                    prompt=sub_prompt,
                    timestamp=timestamp,
                    update_target=segment_ctx.update_target,
                    project_name=segment_ctx.project_name,
                    history_sort_key=segment_ctx.history_sort_key,
                    is_home_mode=segment_ctx.is_home_mode,
                    vcs_ref=segment_ctx.vcs_ref,
                    deferred_workspace=has_wait,
                    local_xprompts_file=local_xprompts_file,
                    extra_env=slot_extra_env or None,
                )
            results.append(result)
            last_project_name = segment_ctx.project_name

            if on_agent_spawned is not None:
                on_agent_spawned()

        previous_agent_name = last_planned_name
        # Fall back to the legacy naming poll only when the next segment has
        # a bare %wait and the previous agent name could not be planned.
        if next_segment_needs_name and previous_agent_name is None:
            assert last_timestamp is not None
            assert last_project_name is not None
            artifacts_dir = create_artifacts_directory(
                "ace-run",
                project_name=last_project_name,
                timestamp=last_timestamp,
            )
            # The artifacts dir is already created by the runner; we just
            # need the path to poll agent_meta.json.
            with timer.stage("multi_prompt_naming_wait", segment_index=i):
                agent_name = _wait_for_agent_naming(artifacts_dir)
            if agent_name:
                previous_agent_name = agent_name
                print(f"  Agent {i + 1}/{len(segments)} named '{agent_name}'")
            else:
                print(f"  Agent {i + 1}/{len(segments)} naming timed out, continuing")
    timer.finish(outcome="ok", launched=len(results))


# Import sentinel at module level (after function definitions to avoid
# circular import issues at class-definition time).
from sase.xprompt.models import UNSET as _UNSET  # noqa: E402
