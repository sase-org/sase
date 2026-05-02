"""Artifact and workflow-reference helpers for agent execution plans."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


def write_plan_path_artifact(artifacts_dir: str, plan_path: str) -> None:
    """Write plan_path.json to the artifacts directory.

    This allows the TUI workflow loader to find the plan file and display
    it in the file panel for the .plan agent entry.
    """
    plan_path_file = Path(artifacts_dir) / "plan_path.json"
    try:
        with open(plan_path_file, "w", encoding="utf-8") as f:
            json.dump({"plan_path": plan_path}, f)
    except OSError:
        pass


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

    # Extract VCS workflow name from tag (e.g., "#hg:sase " -> "hg")
    vcs_name: str | None = None
    if vcs_tag:
        m = re.match(r"#(\w+)", vcs_tag)
        if m:
            vcs_name = m.group(1)

    # Only roll over workflows tagged with "rollover".
    # Backward compat: if no entry has a "tags" key at all, roll over
    # all non-VCS workflows (legacy behavior).
    has_any_tags = any("tags" in w for w in workflows)

    refs: list[str] = []
    for wf in workflows:
        name = wf["name"]
        wf_tags = wf.get("tags", [])
        if name == vcs_name or (vcs_tag and "vcs" in wf_tags):
            continue
        if has_any_tags and "rollover" not in wf_tags:
            continue
        args = wf.get("args", {})
        if not args:
            refs.append(f"#{name}")
        elif len(args) == 1:
            value = next(iter(args.values()))
            refs.append(f"#{name}:{value}")
        else:
            arg_parts = [f"{k}={v}" for k, v in args.items()]
            refs.append(f"#{name}({', '.join(arg_parts)})")

    if not refs:
        return ""
    return " ".join(refs) + " "
