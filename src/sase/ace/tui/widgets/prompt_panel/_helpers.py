"""Helper functions for the agent prompt panel widget."""

import json
from pathlib import Path
from typing import Any

from ...models.agent import Agent


def get_status_indicator(status: str) -> str:
    """Get a status indicator emoji/symbol.

    Args:
        status: The status string.

    Returns:
        A status indicator character.
    """
    indicators = {
        "completed": "[OK]",
        "in_progress": "[...]",
        "pending": "[ ]",
        "skipped": "[SKIP]",
        "failed": "[FAIL]",
        "waiting_hitl": "[WAIT]",
    }
    return indicators.get(status, f"[{status}]")


def format_output(output: Any) -> str:
    """Format step output for display.

    Args:
        output: The output data (dict, list, or primitive).

    Returns:
        Formatted string representation.
    """
    if output is None:
        return "(none)"

    if isinstance(output, dict):
        # Unwrap _data or _raw if present
        display_data = output.get("_data", output.get("_raw", output))
        if isinstance(display_data, str):
            return display_data
        try:
            return json.dumps(display_data, indent=2, default=str)
        except Exception:
            return str(display_data)
    elif isinstance(output, list):
        try:
            return json.dumps(output, indent=2, default=str)
        except Exception:
            return str(output)
    else:
        return str(output)


def format_meta_key(key: str) -> str:
    """Format a meta_* key for display.

    Strips the 'meta_' prefix, replaces underscores with spaces, and
    title-cases the result.

    Args:
        key: The raw meta key (e.g. 'meta_new_cl').

    Returns:
        Formatted display name (e.g. 'New Cl').
    """
    return key.removeprefix("meta_").replace("_", " ").title()


SPECIAL_META_KEYS = frozenset({"meta_project", "meta_changespec", "meta_workspace"})


def extract_meta_fields(output: dict[str, Any]) -> list[tuple[str, str]]:
    """Extract meta_* fields from a step output dict.

    Excludes special meta keys (meta_project, meta_changespec, meta_workspace)
    that are rendered in the header section instead.

    Args:
        output: A step output dictionary.

    Returns:
        List of (display_name, value) tuples for meta fields.
    """
    results: list[tuple[str, str]] = []
    for key, value in output.items():
        if key.startswith("meta_") and key not in SPECIAL_META_KEYS:
            results.append((format_meta_key(key), str(value)))
    return results


def aggregate_meta_fields(
    steps: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    """Aggregate meta_* fields from all workflow steps.

    If a raw key appears in more than one step, each occurrence gets a
    ' #N' suffix (N starting at 1).

    Args:
        steps: List of step state dicts (each may have an 'output' dict).

    Returns:
        List of (display_name, value) tuples.
    """
    # First pass: collect all (raw_key, display_name, value) triples and count keys
    entries: list[tuple[str, str, str]] = []
    key_counts: dict[str, int] = {}
    for step in steps:
        output = step.get("output")
        if not isinstance(output, dict):
            continue
        for key, value in output.items():
            if key.startswith("meta_") and key not in SPECIAL_META_KEYS:
                key_counts[key] = key_counts.get(key, 0) + 1
                entries.append((key, format_meta_key(key), str(value)))

    # Second pass: build results, adding #N suffix for duplicates
    counters: dict[str, int] = {}
    results: list[tuple[str, str]] = []
    for raw_key, display_name, value in entries:
        if key_counts[raw_key] > 1:
            counters[raw_key] = counters.get(raw_key, 0) + 1
            display_name = f"{display_name} #{counters[raw_key]}"
        results.append((display_name, value))
    return results


def load_embedded_workflows(agent: Agent) -> list[dict[str, Any]] | None:
    """Load embedded workflow metadata from embedded_workflows.json.

    Uses the step-specific file ``embedded_workflows_{step_name}.json``
    when the agent has a ``step_name``; falls back to the shared file
    only when ``step_name`` is None.

    Args:
        agent: The agent to load metadata for.

    Returns:
        List of workflow metadata dicts, or None if not found.
    """
    artifacts_dir = agent.get_artifacts_dir()
    if artifacts_dir is None:
        return None

    artifacts_path = Path(artifacts_dir)

    # Try step-specific file first (multi-step workflows)
    if agent.step_name:
        step_file = artifacts_path / f"embedded_workflows_{agent.step_name}.json"
        if step_file.exists():
            try:
                with open(step_file, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list) and data:
                    return data
            except Exception:
                pass
        # Step has no embedded workflows — don't fall back to shared file
        return None

    # Fall back to shared file (only for agents without step_name)
    metadata_file = artifacts_path / "embedded_workflows.json"
    if not metadata_file.exists():
        return None

    try:
        with open(metadata_file, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    if not isinstance(data, list) or not data:
        return None

    return data


def format_embedded_workflows(workflows: list[dict[str, Any]]) -> str:
    """Format embedded workflow metadata for display.

    Args:
        workflows: List of workflow metadata dicts with 'name' and 'args' keys.

    Returns:
        Formatted string like "propose(note=blah), cl".
    """
    parts: list[str] = []
    for wf in workflows:
        name = wf.get("name", "unknown")
        args = wf.get("args", {})
        # Filter out empty string values (e.g., from default args not provided)
        args = {k: v for k, v in args.items() if v != ""}
        if args:
            args_str = ", ".join(f"{k}={v}" for k, v in args.items())
            parts.append(f"{name}({args_str})")
        else:
            parts.append(name)
    return ", ".join(parts)
