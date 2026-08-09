"""Agent reference resolution helpers for the run agent runner."""

import json
import os


def resolve_wait_chat_paths(wait_names: list[str]) -> list[str]:
    """Resolve each waited-for agent name to its ``~/.sase/chats/`` transcript path.

    Called after :func:`wait_for_dependencies` returns, so each completed
    agent should have a ``done.json`` with a ``response_path`` field.  Names
    that can't be resolved or whose agent has no ``response_path`` (e.g. the
    agent failed or crashed before saving a transcript) are skipped with a
    warning; order of the remaining names is preserved, including duplicates.
    """
    from sase.agent.names import resolve_resume_agent_name
    from sase.output import print_status

    resolved: list[str] = []
    for name in wait_names:
        agent = resolve_resume_agent_name(name)
        if agent is None:
            print_status(
                f"wait_chats: no done agent found for '{name}' — skipping",
                "warning",
            )
            continue
        done_path = os.path.join(agent.artifacts_dir, "done.json")
        try:
            with open(done_path, encoding="utf-8") as f:
                done_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
            print_status(
                f"wait_chats: cannot read done.json for '{name}' ({exc}) — skipping",
                "warning",
            )
            continue
        response_path = done_data.get("response_path")
        if not response_path:
            print_status(
                f"wait_chats: agent '{name}' has no response_path — skipping",
                "warning",
            )
            continue
        resolved.append(str(response_path))
    return resolved


def resolve_agent_refs_in_prompt(prompt: str) -> tuple[str, str | None]:
    """Resolve @name agent references in VCS tags.

    Normalizes underscore VCS refs, extracts the VCS tag, checks for
    @name in the ref portion, and replaces it with the agent's patch.

    Returns (resolved_prompt, resolved_vcs_tag).
    """
    from sase.xprompt._parsing import (
        extract_project_from_vcs_tag,
        extract_vcs_workflow_tag,
        normalize_vcs_underscore_refs,
    )

    # Normalize #gh_@a -> #gh:@a so downstream only sees colon form.
    prompt = normalize_vcs_underscore_refs(prompt)

    # Extract the VCS tag (handles leading %directives).
    vcs_tag = extract_vcs_workflow_tag(prompt)
    if not vcs_tag:
        return prompt, None

    # Check if the ref portion is an @name reference.
    ref = extract_project_from_vcs_tag(vcs_tag)
    if not ref or not ref.startswith("@"):
        return prompt, vcs_tag

    agent_name = ref[1:]  # strip leading @
    if not agent_name:
        return prompt, vcs_tag

    # Resolve the agent reference.
    from sase.agent.names import resolve_agent_patch

    patch = resolve_agent_patch(agent_name)

    # Replace @name with the patch in the VCS tag portion.
    new_tag = vcs_tag.replace(f"@{agent_name}", patch)
    resolved_prompt = prompt.replace(vcs_tag, new_tag, 1)

    # Re-extract vcs_tag from the resolved prompt.
    resolved_vcs_tag = extract_vcs_workflow_tag(resolved_prompt)
    return resolved_prompt, resolved_vcs_tag
