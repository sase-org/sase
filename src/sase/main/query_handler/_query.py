"""Core query execution logic."""

import json
import os
import re
from typing import Any

from sase.artifacts import create_artifacts_directory
from sase.history.chat import save_chat_history
from sase.running_field import claim_workspace, release_workspace

from ..utils import ensure_project_file_and_get_workspace_num


def _resolve_vcs_cwd(query: str) -> tuple[str, str] | None:
    """Detect VCS workflow refs in the query and resolve workspace CWD.

    If the query contains a VCS workflow reference (e.g., ``#gh:sase``),
    resolves the ref to the primary workspace directory and changes CWD.
    This ensures that project-specific workflows are discoverable and
    CWD-relative paths in workflow steps work correctly.

    Mirrors the TUI behavior where the subprocess CWD is set to the
    resolved workspace directory before the workflow runs.

    Args:
        query: The query text.

    Returns:
        A ``(project_name, vcs_ref)`` tuple, or ``None`` if no VCS ref
        was found.  ``vcs_ref`` is the raw ref extracted from the
        ``#type:ref`` pattern (e.g., "yserve_batch_create_update").
    """
    if "#" not in query:
        return None

    from sase.workspace_provider import get_workflow_names, resolve_ref
    from sase.xprompt._parsing import normalize_vcs_underscore_refs

    normalized = normalize_vcs_underscore_refs(query)

    for workflow_type in get_workflow_names():
        pattern = rf"#({re.escape(workflow_type)}):([a-zA-Z0-9_.~/-]+)"
        match = re.search(pattern, normalized)
        if match:
            ref = match.group(2)
            try:
                resolved = resolve_ref(ref, workflow_type)
            except (ValueError, Exception):
                continue
            if resolved and resolved.primary_workspace_dir:
                os.chdir(resolved.primary_workspace_dir)
                # Clear cached project detection since CWD changed
                from sase.xprompt.loader import detect_project

                detect_project.cache_clear()
                return resolved.project_name or ref, ref

    return None


def run_query(
    query: str,
    previous_history: str | None = None,
) -> None:
    """Execute a query through the unified workflow path.

    Creates an anonymous workflow and routes through WorkflowExecutor,
    producing workflow_state.json and step markers for TUI visibility.

    Args:
        query: The query to send to the agent.
        previous_history: Optional previous conversation history to continue from.
    """
    from sase.core.time import generate_timestamp
    from sase.xprompt.models import create_anonymous_workflow
    from sase.xprompt.workflow_runner import execute_workflow

    # Resolve VCS refs early so project-specific workflows are discoverable
    # and CWD-relative paths in workflow steps work correctly.  This mirrors
    # the TUI behavior where subprocess CWD is set before workflow execution.
    vcs_result = _resolve_vcs_cwd(query)
    if vcs_result is not None:
        vcs_project, vcs_ref = vcs_result
    else:
        vcs_project, vcs_ref = None, None

    # Get project info for workspace claiming (creates project file if needed)
    project_file, workspace_num, _ = ensure_project_file_and_get_workspace_num()

    # Resolve cl_name from VCS ref (the actual CL name, e.g. "yserve_batch_create_update")
    cl_name = vcs_ref
    if cl_name is None and project_file:
        cl_name = os.path.basename(os.path.dirname(project_file))

    agent_model: str | None = None
    agent_llm_provider: str | None = None
    agent_vcs_provider: str | None = None

    # Resolve aliases before saving so history stores canonical names
    from sase.xprompt import resolve_xprompt_aliases

    query = resolve_xprompt_aliases(query)

    # Save prompt to history immediately (only for new queries, not resume)
    # This ensures the prompt is visible in `sase run .` from other terminals
    if previous_history is None:
        from sase.history.prompt import add_or_update_prompt

        add_or_update_prompt(query)

    # Parse user-prompt frontmatter for local xprompts (after history save
    # so prompt history retains the original frontmatter).
    from sase.agent.multi_prompt import parse_multi_prompt

    multi = parse_multi_prompt(query)
    local_xprompts = multi.local_xprompts
    if multi.frontmatter is not None:
        query = "\n---\n".join(multi.segments)

    try:
        # Build the full prompt
        if previous_history:
            full_prompt = f"""# Previous Conversation

{previous_history}

---

# New Query

{query}"""
        else:
            full_prompt = query

        # Convert escaped newlines to actual newlines
        full_prompt = full_prompt.replace("\\n", "\n")

        # Capture start timestamp for accurate duration calculation
        shared_timestamp = generate_timestamp()

        # Create artifacts directory for prompt persistence
        artifacts_timestamp: str | None = None
        try:
            artifacts_dir: str | None = create_artifacts_directory("run")
            # Extract timestamp from the directory path (last component)
            if artifacts_dir:
                artifacts_timestamp = os.path.basename(artifacts_dir)
        except RuntimeError:
            # Not in a recognized project - skip artifacts
            artifacts_dir = None

        # Save raw prompt for TUI display (matches daemon runner behavior)
        if artifacts_dir:
            raw_xprompt_path = os.path.join(artifacts_dir, "raw_xprompt.md")
            with open(raw_xprompt_path, "w", encoding="utf-8") as f:
                f.write(query)

        # Write agent_meta.json for TUI model/provider display
        if artifacts_dir:
            from sase.xprompt.directives import extract_prompt_directives

            _, directives = extract_prompt_directives(full_prompt)

            from sase.llm_provider.registry import (
                get_default_provider_name,
                get_provider,
                resolve_model_provider,
            )

            if directives.model:
                resolved_provider, agent_model = resolve_model_provider(
                    directives.model
                )
                agent_llm_provider = resolved_provider or get_default_provider_name()
            else:
                agent_llm_provider = get_default_provider_name()
                provider = get_provider()
                agent_model = provider.resolve_model_name()

            from sase.vcs_provider._registry import detect_vcs

            vcs_name = detect_vcs(os.getcwd())
            if vcs_name:
                from sase.workspace_provider import get_display_name_by_vcs

                agent_vcs_provider = get_display_name_by_vcs(vcs_name)

            agent_meta: dict[str, Any] = {"pid": os.getpid()}
            if agent_model:
                agent_meta["model"] = agent_model
            if agent_llm_provider:
                agent_meta["llm_provider"] = agent_llm_provider
            if agent_vcs_provider:
                agent_meta["vcs_provider"] = agent_vcs_provider

            meta_path = os.path.join(artifacts_dir, "agent_meta.json")
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(agent_meta, f, indent=2)

        # Write initial workflow_state.json so the TUI can discover
        # this run immediately (before WorkflowExecutor overwrites it).
        if artifacts_dir:
            initial_state: dict[str, Any] = {
                "status": "running",
                "appears_as_agent": True,
                "pid": os.getpid(),
                "context": {"cl_name": cl_name or "unknown"},
                "steps": [],
                "current_step_index": 0,
                "workflow_name": "run",
            }
            init_state_path = os.path.join(artifacts_dir, "workflow_state.json")
            with open(init_state_path, "w", encoding="utf-8") as f:
                json.dump(initial_state, f, indent=2)

        # Claim workspace with artifacts timestamp for prompt lookup
        if project_file and workspace_num:
            claim_workspace(
                project_file,
                workspace_num,
                "run",
                os.getpid(),
                cl_name,
                artifacts_timestamp=artifacts_timestamp,
            )

        # Create anonymous workflow and execute through WorkflowExecutor
        anon_workflow = create_anonymous_workflow(full_prompt)
        if local_xprompts:
            anon_workflow.xprompts = local_xprompts

        # Inject implicit workflow context variables (mirrors run_workflow_runner.py)
        workflow_named_args: dict[str, Any] = {}
        if cl_name:
            workflow_named_args["cl_name"] = cl_name
        if project_file:
            workflow_named_args["project_file"] = project_file
        if workspace_num:
            workflow_named_args["workspace_num"] = workspace_num

        workflow_error: Exception | None = None
        try:
            result = execute_workflow(
                anon_workflow.name,
                [],
                workflow_named_args,
                artifacts_dir=artifacts_dir,
                workflow_obj=anon_workflow,
                project=vcs_project,
            )
        except Exception as e:
            workflow_error = e
            result = None

        # Write done.json completion marker for TUI visibility
        if artifacts_dir:
            from sase.axe.run_agent_phases import build_done_marker

            outcome = "failed" if workflow_error else "completed"
            done_marker = build_done_marker(
                cl_name or "unknown",
                project_file or "",
                shared_timestamp,
                artifacts_timestamp or "",
                workspace_num or 0,
                "",  # no output log for inline runs
                outcome,
                agent_model=agent_model,
                agent_llm_provider=agent_llm_provider,
                agent_vcs_provider=agent_vcs_provider,
            )
            if result and result.response_text:
                response_path = os.path.join(artifacts_dir, "response.md")
                with open(response_path, "w", encoding="utf-8") as f:
                    f.write(result.response_text)
                done_marker["response_path"] = response_path
            if workflow_error:
                import traceback

                done_marker["error"] = (
                    f"{type(workflow_error).__qualname__}: {workflow_error}"
                )
                done_marker["traceback"] = "".join(
                    traceback.format_exception(workflow_error)
                )

            done_path = os.path.join(artifacts_dir, "done.json")
            with open(done_path, "w", encoding="utf-8") as f:
                json.dump(done_marker, f, indent=2)

        # Re-raise workflow errors after writing done.json
        if workflow_error:
            raise workflow_error
        assert result is not None

        # Extract response text for chat history
        response_content = result.response_text or ""

        # Prepare and save chat history
        saved_path = save_chat_history(
            prompt=query,
            response=response_content,
            workflow="run",
            previous_history=previous_history,
            timestamp=shared_timestamp,
        )

        print(f"\nChat history saved to: {saved_path}")
    finally:
        # Release workspace when done
        if project_file and workspace_num:
            release_workspace(project_file, workspace_num, "run", cl_name)
