"""Artifact resolution and content retrieval for Agent instances."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from sase.ace.tui.models.agent import AgentType

if TYPE_CHECKING:
    from sase.ace.tui.models.agent import Agent


def get_artifacts_dir(agent: Agent) -> str | None:
    """Get the artifacts directory path for this agent.

    Returns:
        Path to the artifacts directory, or None if it cannot be determined.
    """
    # If we have an explicit artifacts_dir (from marker files), use it directly
    if agent.artifacts_dir and os.path.isdir(agent.artifacts_dir):
        return agent.artifacts_dir

    # Extract project name from project_file
    # Format: ~/.sase/projects/<project>/<project>.gp
    project_path = Path(agent.project_file)
    project_name = project_path.parent.name

    # Determine workflow name based on agent type
    if agent.agent_type == AgentType.RUNNING:
        workflow = agent.workflow or "run"
        # Extract base workflow: "ace(run)-timestamp" -> "ace-run"
        if workflow.startswith("ace(run)"):
            workflow_name = "ace-run"
        elif workflow.startswith("axe(fix-hook)"):
            workflow_name = "fix-hook"
        elif workflow.startswith("axe(crs)"):
            workflow_name = "crs"
        elif workflow.startswith("axe(mentor)"):
            # "axe(mentor)-complete-TIMESTAMP" -> "mentor-complete"
            parts = workflow.split("-")
            workflow_name = f"mentor-{parts[1]}" if len(parts) >= 2 else "mentor"
        elif workflow.startswith("mentor(") and workflow.endswith(")"):
            # "mentor(code_quality)" -> artifacts dir "mentor-code_quality"
            profile = workflow[7:-1]
            workflow_name = f"mentor-{profile}"
        elif workflow == "mentor" and agent.mentor_name:
            # ChangeSpec-sourced mentor: workflow="mentor", mentor_name="code_quality"
            # -> artifacts dir "mentor-code_quality"
            workflow_name = f"mentor-{agent.mentor_name}"
        elif workflow == "fix_hook":
            # VCS workspace claim uses "fix_hook" (from xprompt
            # workflow_label) but artifacts dir is "fix-hook"
            workflow_name = "fix-hook"
        else:
            workflow_name = workflow
    elif agent.agent_type == AgentType.WORKFLOW:
        # Workflow artifacts: workflow-{name}, or ace-run for appears_as_agent
        if agent.workflow:
            base_workflow = (
                agent.workflow.split("/")[-1]
                if "/" in agent.workflow
                else agent.workflow
            )
            # appears_as_agent workflows may use ace-run/ artifacts dir
            if agent.appears_as_agent:
                ace_run_dir = os.path.expanduser(
                    f"~/.sase/projects/{project_name}/artifacts/ace-run"
                )
                if os.path.isdir(ace_run_dir):
                    timestamp = extract_artifacts_timestamp(agent)
                    if timestamp:
                        candidate = os.path.join(ace_run_dir, timestamp)
                        if os.path.isdir(candidate):
                            return candidate
            workflow_name = f"workflow-{base_workflow}"
        else:
            return None
    else:
        return None

    # Extract and convert timestamp from raw_suffix
    # raw_suffix format: <agent>-<PID>-YYmmdd_HHMMSS or similar
    # artifacts_dir expects: YYYYmmddHHMMSS
    if agent.raw_suffix is None:
        return None

    timestamp = extract_artifacts_timestamp(agent)
    if timestamp is None:
        return None

    # Construct path
    artifacts_dir = os.path.expanduser(
        f"~/.sase/projects/{project_name}/artifacts/{workflow_name}/{timestamp}"
    )

    if os.path.isdir(artifacts_dir):
        return artifacts_dir

    return None


def extract_artifacts_timestamp(agent: Agent) -> str | None:
    """Extract and convert timestamp from raw_suffix to artifacts format.

    For RUNNING agents: raw_suffix is already YYYYmmddHHMMSS (14 chars)
    For ChangeSpec-sourced agents: raw_suffix uses YYmmdd_HHMMSS format (13 chars with underscore)
    artifacts_dir expects: YYYYmmddHHMMSS format (14 chars, no underscore)

    Returns:
        Converted timestamp string, or None if parsing fails.
    """
    if agent.raw_suffix is None:
        return None

    # For RUNNING agents, raw_suffix is the timestamp directly (14 chars)
    if len(agent.raw_suffix) == 14 and agent.raw_suffix.isdigit():
        return agent.raw_suffix

    # Extract timestamp part from suffix
    ts: str | None = None

    if "-" in agent.raw_suffix:
        parts = agent.raw_suffix.split("-")
        if len(parts) >= 2:
            ts = parts[-1]
    else:
        ts = agent.raw_suffix

    # Validate and convert format: YYmmdd_HHMMSS -> YYYYmmddHHMMSS
    if ts and len(ts) == 13 and ts[6] == "_":
        # Add century prefix and remove underscore
        return f"20{ts[:6]}{ts[7:]}"

    return None


def get_raw_xprompt_content(agent: Agent) -> str | None:
    """Get the raw xprompt content (before preprocessing/expansion).

    Returns:
        Raw xprompt content string, or None if not available.
    """
    artifacts_dir = get_artifacts_dir(agent)
    if artifacts_dir is None:
        return None
    raw_path = os.path.join(artifacts_dir, "raw_xprompt.md")
    try:
        with open(raw_path, encoding="utf-8") as f:
            return f.read()
    except (FileNotFoundError, OSError):
        return None


def get_live_reply_content(agent: Agent) -> str | None:
    """Get the live reply content for running agents.

    Returns:
        Live reply content string, or None if not available.
    """
    artifacts_dir = get_artifacts_dir(agent)
    if artifacts_dir is None:
        return None
    path = os.path.join(artifacts_dir, "live_reply.md")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (FileNotFoundError, OSError):
        return None


def get_timestamped_reply_chunks(agent: Agent) -> list[tuple[str, str]] | None:
    """Load live reply split into timestamped chunks.

    Returns:
        List of (iso_timestamp, content_text) tuples, or None if timestamps
        unavailable. Falls back to None so callers can use the un-timestamped
        path.
    """
    artifacts_dir = get_artifacts_dir(agent)
    if artifacts_dir is None:
        return None

    timestamps_path = os.path.join(artifacts_dir, "live_reply_timestamps.jsonl")
    reply_path = os.path.join(artifacts_dir, "live_reply.md")

    try:
        with open(timestamps_path, encoding="utf-8") as f:
            lines = f.readlines()
    except (FileNotFoundError, OSError):
        return None

    entries: list[tuple[int, str]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            entries.append((data["byte_offset"], data["timestamp"]))
        except (json.JSONDecodeError, KeyError):
            continue

    if not entries:
        return None

    try:
        with open(reply_path, "rb") as f:
            content_bytes = f.read()
    except (FileNotFoundError, OSError):
        return None

    chunks: list[tuple[str, str]] = []
    for i, (offset, timestamp) in enumerate(entries):
        end = entries[i + 1][0] if i + 1 < len(entries) else len(content_bytes)
        chunk_text = content_bytes[offset:end].decode("utf-8", errors="replace")
        chunks.append((timestamp, chunk_text))

    return chunks if chunks else None


def get_response_content(agent: Agent) -> str | None:
    """Get the response content for DONE agents.

    Returns:
        Response content string, or None if not available.
    """
    if agent.response_path is None:
        return None
    try:
        with open(os.path.expanduser(agent.response_path), encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def get_chat_response_content(agent: Agent) -> str | None:
    """Get response content from agent_meta.json chat_path.

    Fallback for agents where the live reply and response path are empty
    (e.g., Gemini thinking models killed during the plan phase).

    Returns:
        Chat response content string, or None if not available.
    """
    artifacts_dir = get_artifacts_dir(agent)
    if artifacts_dir is None:
        return None
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    chat_path = data.get("chat_path")
    if not chat_path:
        return None
    try:
        with open(os.path.expanduser(chat_path), encoding="utf-8") as f:
            return f.read()
    except (FileNotFoundError, OSError):
        return None
