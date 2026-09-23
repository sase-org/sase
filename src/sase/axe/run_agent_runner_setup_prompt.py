"""Prompt preprocessing for ``run_agent_runner``.

Alias resolution, raw-prompt capture, xprompt expansion (including the
launch-deferred fork set), and the launch-time prompt helpers.
"""

import json
import os
import sys
from typing import Any

from sase.core.revival_inputs import capture_revival_inputs

__all__ = [
    "build_output_variable_namespaces",
    "expand_deferred_launch_xprompts",
    "preprocess_prompt_xprompts",
    "print_agent_start_banner",
    "write_submitted_xprompt_artifact",
]


def preprocess_prompt_xprompts(
    prompt: str, artifacts_dir: str
) -> tuple[str, str | None, str]:
    """Resolve aliases, save raw, expand xprompt references.

    Returns ``(prompt, vcs_tag, raw_resolved_prompt)``. The VCS workflow tag
    and raw prompt are captured after alias resolution but before xprompt
    expansion so follow-up naming and chat-resume decisions can use the
    original top-level references.
    """
    from sase.project_aliases import canonicalize_project_aliases_in_prompt
    from sase.xprompt import resolve_xprompt_aliases
    from sase.xprompt._parsing import extract_vcs_workflow_tag
    from sase.xprompt.processor import (
        LAUNCH_DEFERRED_XPROMPT_NAMES,
        process_xprompt_references,
    )

    prompt = canonicalize_project_aliases_in_prompt(prompt)
    prompt = resolve_xprompt_aliases(prompt)
    raw_resolved_prompt = prompt
    vcs_tag = extract_vcs_workflow_tag(prompt)

    raw_xprompt_path = os.path.join(artifacts_dir, "raw_xprompt.md")
    with open(raw_xprompt_path, "w", encoding="utf-8") as f:
        f.write(prompt)

    # Capture launch-boundary xprompt usage (e.g. #plan) into the shared
    # xprompts.json before expansion erases the references. Use the same
    # alias-resolved text persisted to raw_xprompt.md so the collector's
    # alias/VCS-underscore handling matches the expansion path. The root
    # agent row reads this file; workflow steps only write step-specific
    # files (see write_used_xprompts step_only). Best-effort: metadata
    # capture must never take down a detached agent launch.
    try:
        from sase.xprompt.used_xprompts import (
            SASE_LAUNCH_SWARM_XPROMPTS,
            write_used_xprompts,
        )

        encoded_swarm_xprompts = os.environ.get(SASE_LAUNCH_SWARM_XPROMPTS)
        swarm_xprompts = (
            json.loads(encoded_swarm_xprompts) if encoded_swarm_xprompts else None
        )
        if swarm_xprompts is not None and (
            not isinstance(swarm_xprompts, list)
            or not all(isinstance(name, str) for name in swarm_xprompts)
        ):
            raise ValueError(
                f"{SASE_LAUNCH_SWARM_XPROMPTS} must be a JSON array of strings"
            )
        write_used_xprompts(
            artifacts_dir,
            prompt,
            swarm_xprompts=swarm_xprompts,
        )
    except Exception as e:
        print(f"Warning: Failed to write xprompt metadata: {e}", file=sys.stderr)

    # Archive launch-boundary prompt files outside the live artifacts dir so
    # later chop/cleanup cannot orphan publication. Best-effort: capture must
    # never take down a detached agent launch.
    try:
        capture_revival_inputs(artifacts_dir)
    except Exception as e:
        print(f"Warning: Failed to archive revival inputs: {e}", file=sys.stderr)

    prompt = process_xprompt_references(
        prompt,
        defer_xprompt_names=LAUNCH_DEFERRED_XPROMPT_NAMES,
    )
    return prompt, vcs_tag, raw_resolved_prompt


def expand_deferred_launch_xprompts(
    prompt: str,
    artifacts_dir: str,
    *,
    extra_xprompts: dict[str, Any] | None = None,
) -> str:
    """Expand launch-deferred fork references after dependency admission.

    Ordinary xprompts are expanded first in case a refreshed definition now
    introduces a fork.  Embedded workflow expansion is then restricted to the
    launch-deferred set so VCS and completion workflows keep their established
    execution timing inside the agent workflow.

    ``SASE_ARTIFACTS_DIR`` is set to *artifacts_dir* for the duration of this
    call and restored afterward (this run's own value is not published by
    ``publish_phase_env()`` until later in ``run_execution_loop()``). A bare
    ``#fork`` resolves its parent through
    ``_resolve_default_agent_name(exclude_artifacts_dir=...)``, which reads
    ``SASE_ARTIFACTS_DIR`` to exclude the run being launched from its own
    resolution; without this scoping that self-exclusion silently no-ops and
    a named run can resolve `#fork` to itself. The restore is scoped narrowly
    here rather than calling ``publish_phase_env()`` early, which also sets
    ``SASE_AGENT_TIMESTAMP`` and would change the unset/inherited snapshot
    that ``run_execution_loop()`` takes of that variable before publishing it.
    """
    from sase.main.query_handler import expand_embedded_workflows_in_query
    from sase.xprompt.processor import (
        LAUNCH_DEFERRED_XPROMPT_NAMES,
        process_xprompt_references,
    )

    prompt = process_xprompt_references(
        prompt,
        extra_xprompts=extra_xprompts,
    )

    previous_artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    os.environ["SASE_ARTIFACTS_DIR"] = artifacts_dir
    try:
        prompt, embedded_workflows = expand_embedded_workflows_in_query(
            prompt,
            artifacts_dir,
            only_workflow_names=LAUNCH_DEFERRED_XPROMPT_NAMES,
            preserve_existing_xprompt_metadata=True,
        )
    finally:
        if previous_artifacts_dir is None:
            os.environ.pop("SASE_ARTIFACTS_DIR", None)
        else:
            os.environ["SASE_ARTIFACTS_DIR"] = previous_artifacts_dir

    workflows_with_post_steps = [
        result.workflow_name for result in embedded_workflows if result.post_steps
    ]
    if workflows_with_post_steps:
        names = ", ".join(sorted(set(workflows_with_post_steps)))
        raise RuntimeError("Launch-deferred workflows cannot have post-steps: " + names)
    return prompt


def write_submitted_xprompt_artifact(artifacts_dir: str, submitted_xprompt: str) -> str:
    """Persist the launch-boundary prompt without alias or xprompt expansion."""
    path = os.path.join(artifacts_dir, "submitted_xprompt.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(submitted_xprompt)
    return path


def print_agent_start_banner(
    *, cl_name: str, workspace_dir: str, workflow_name: str, prompt: str
) -> None:
    print("Starting agent run")
    print(f"Patch: {cl_name}")
    print(f"Workspace: {workspace_dir}")
    print(f"Workflow: {workflow_name}")
    print()
    print("=== Prompt ===")
    print(prompt)
    print("==============")
    print()


def build_output_variable_namespaces(wait_names: list[str]) -> dict[str, Any]:
    from sase.agent.output_variable_context import (
        SASE_AGENT_VAR_UPSTREAMS_ENV,
        build_agent_output_variable_context,
    )

    return build_agent_output_variable_context(
        upstreams_json=os.environ.get(SASE_AGENT_VAR_UPSTREAMS_ENV),
        wait_names=wait_names,
    )
