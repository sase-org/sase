"""Shared xprompt-highlighting context for agent prompt panels."""

from __future__ import annotations

from pathlib import Path

from sase.xprompt import extract_project_from_vcs_tag, extract_vcs_workflow_tag

from ...models.agent import Agent


def known_xprompt_skill_names(
    panel: object,
    agent: Agent,
    raw_xprompt: str,
) -> frozenset[str]:
    """Return warm, memory-only skill names for an agent's project context."""
    project: str | None = None
    try:
        vcs_tag = extract_vcs_workflow_tag(raw_xprompt)
        if vcs_tag is not None:
            project = extract_project_from_vcs_tag(vcs_tag)
    except Exception:
        pass

    if project is None and agent.project_file:
        project = Path(agent.project_file).parent.name or None

    try:
        app = getattr(panel, "app", None)
        getter = getattr(app, "get_prompt_catalog_assist_entries", None)
        if not callable(getter):
            return frozenset()
        entries = getter(project, schedule=True)
        if entries is None:
            return frozenset()
        return frozenset(
            entry.name
            for entry in entries
            if getattr(entry, "is_skill", False)
            and isinstance(getattr(entry, "name", None), str)
        )
    except Exception:
        return frozenset()


__all__ = ["known_xprompt_skill_names"]
