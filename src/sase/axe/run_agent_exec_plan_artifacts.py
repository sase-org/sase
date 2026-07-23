"""Artifact and workflow-reference helpers for agent execution plans."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from sase.core.artifact_file_facade import store_explicit_artifact_file
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)

logger = logging.getLogger(__name__)


def write_plan_path_artifact(artifacts_dir: str, plan_path: str) -> None:
    """Write plan_path.json to the artifacts directory.

    This allows the TUI workflow loader to find the plan file and display
    it in the file panel for the .plan agent entry.
    """
    plan_path_file = Path(artifacts_dir) / "plan_path.json"
    try:
        with open(plan_path_file, "w", encoding="utf-8") as f:
            json.dump({"plan_path": plan_path}, f)
        update_agent_artifact_index_for_marker_mutation(artifacts_dir)
    except OSError:
        pass


def store_followup_prompt_artifact(
    artifacts_dir: str,
    prompt: str,
    *,
    label: str = "Full follow-up prompt",
) -> None:
    """Store the rebuilt prompt as an explicit artifact for a follow-up agent."""
    try:
        artifacts_path = Path(artifacts_dir).expanduser()
        artifacts_path.mkdir(parents=True, exist_ok=True)
        prompt_path = artifacts_path / "followup_prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        store_explicit_artifact_file(
            prompt_path,
            artifacts_path,
            label=label,
            kind="markdown",
        )
    except Exception:
        logger.warning("Failed to store follow-up prompt artifact", exc_info=True)


def embedded_workflow_refs_from_metadata(
    workflows: object,
    vcs_tag: str | None,
) -> str:
    """Render rollover workflow references from expanded-workflow metadata."""
    if not isinstance(workflows, list):
        return ""
    workflow_items = [item for item in workflows if isinstance(item, dict)]

    # Extract the workspace workflow name from the tag (e.g. "#gh:sase " -> "gh")
    vcs_name: str | None = None
    if vcs_tag:
        m = re.match(r"#(\w+)", vcs_tag)
        if m:
            vcs_name = m.group(1)

    # Only roll over workflows tagged with "rollover".
    # Backward compat: if no entry has a "tags" key at all, roll over
    # all non-VCS workflows (legacy behavior).
    has_any_tags = any("tags" in workflow for workflow in workflow_items)

    refs: list[str] = []
    for workflow in workflow_items:
        name = workflow.get("name")
        if not isinstance(name, str) or not name:
            continue
        wf_tags = workflow.get("tags", [])
        if name == vcs_name or (vcs_tag and "vcs" in wf_tags):
            continue
        if has_any_tags and "rollover" not in wf_tags:
            continue
        args = workflow.get("args", {})
        if not isinstance(args, dict) or not args:
            refs.append(f"#{name}")
        elif len(args) == 1:
            value = next(iter(args.values()))
            refs.append(f"#{name}:{value}")
        else:
            arg_parts = [f"{key}={value}" for key, value in args.items()]
            refs.append(f"#{name}({', '.join(arg_parts)})")

    if not refs:
        return ""
    return " ".join(refs) + " "


def get_embedded_workflow_refs(artifacts_dir: str, vcs_tag: str | None) -> str:
    """Reconstruct non-VCS embedded workflow refs from artifacts metadata.

    Reads embedded_workflows.json (written during workflow expansion before
    the agent is killed) and returns a string of workflow references
    (e.g., ``"#propose "``) to append to follow-up agent prompts so their
    post-steps run after the follow-up agent completes.
    """
    metadata_path = os.path.join(artifacts_dir, "embedded_workflows.json")
    try:
        with open(metadata_path, encoding="utf-8") as f:
            workflows = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return ""

    return embedded_workflow_refs_from_metadata(workflows, vcs_tag)
