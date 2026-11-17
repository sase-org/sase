"""Compact prompt-step marker enrichment for list row constructors."""

from __future__ import annotations

from collections.abc import Iterable

from sase.core.agent_scan_list_wire import AgentArtifactListStepWire

from ..agent import Agent


def enrich_agent_from_compact_prompt_steps(
    agent: Agent,
    prompt_steps: Iterable[AgentArtifactListStepWire],
) -> None:
    """Merge compact prompt-step ``meta_*`` output facts into ``step_output``.

    Compact twin of :func:`enrich_agent_from_prompt_markers_wire`: the
    projection already narrowed each step output to ``meta_*`` facts (plus
    a separate ``diff_path``), so the merge reads the ``meta`` map
    directly. Records stay in file-name order (matching the filesystem
    ``glob`` + ``sorted`` order) so iteration order is deterministic.
    """
    meta_fields: dict[str, str] = {}
    for step in prompt_steps:
        output = step.output
        if output is None:
            continue
        for k, v in output.meta.items():
            if k.startswith("meta_") and v:
                meta_fields[k] = str(v)
    if meta_fields:
        if agent.step_output is None:
            agent.step_output = {}
        agent.step_output.update(meta_fields)
