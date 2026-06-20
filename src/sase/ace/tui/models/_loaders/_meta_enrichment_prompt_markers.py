"""Prompt-step marker enrichment helpers."""

from __future__ import annotations

import json
from pathlib import Path

from sase.core.agent_scan_wire import PromptStepMarkerWire

from ._json_cache import load_json_cached
from ..agent import Agent


def enrich_agent_from_prompt_markers(agent: Agent, artifacts_dir: str) -> None:
    """Read prompt_step_*.json markers and populate meta_* fields on step_output.

    Args:
        agent: The Agent to enrich (modified in place).
        artifacts_dir: Path to the artifacts directory.
    """
    artifacts_path = Path(artifacts_dir)
    meta_fields: dict[str, str] = {}
    for marker_file in sorted(artifacts_path.glob("prompt_step_*.json")):
        try:
            data = load_json_cached(marker_file)
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        output = data.get("output")
        if isinstance(output, dict):
            for k, v in output.items():
                if k.startswith("meta_") and v:
                    meta_fields[k] = str(v)
    if meta_fields:
        if agent.step_output is None:
            agent.step_output = {}
        agent.step_output.update(meta_fields)


def enrich_agent_from_prompt_markers_wire(
    agent: Agent,
    prompt_steps: list[PromptStepMarkerWire],
) -> None:
    """Snapshot-aware mirror of :func:`enrich_agent_from_prompt_markers`.

    Collects ``meta_*`` fields from each prompt step's ``output`` dict and
    merges them into ``agent.step_output``. Records in the snapshot are
    already sorted by ``file_name`` (matching the filesystem ``glob`` +
    ``sorted`` order) so iteration order is deterministic.
    """
    meta_fields: dict[str, str] = {}
    for step in prompt_steps:
        output = step.output
        if not isinstance(output, dict):
            continue
        for k, v in output.items():
            if k.startswith("meta_") and v:
                meta_fields[k] = str(v)
    if meta_fields:
        if agent.step_output is None:
            agent.step_output = {}
        agent.step_output.update(meta_fields)
