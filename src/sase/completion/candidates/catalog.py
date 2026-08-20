"""Cheap in-process catalogs for live completion values.

The fetchers themselves live in the ``catalog_*`` sibling modules, grouped by
where their values come from; this module is only the kind -> fetcher table.

Each fetcher imports its real dependencies inside the function so requesting
one kind never pays for the others. These modules must stay off the
``sase.ace`` / ``sase.main.parser`` / ``rich`` / ``textual`` import set: the
candidates fast path forbids those packages. That means no
``sase.sdd`` / ``sase.bead`` / ``sase.workspace_provider`` / ``sase.xprompt``
/ ``sase.llm_provider`` package imports (their ``__init__`` modules pull the
forbidden set), at module scope or inside a fetcher.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sase.completion.candidates.catalog_agents import (
    agent_candidates,
    agent_source_path,
    artifact_candidates,
    artifact_source_path,
    monitor_candidates,
    monitor_source_path,
    proc_candidates,
    proc_source_path,
)
from sase.completion.candidates.catalog_build import (
    artifact_relation_candidates,
    artifact_relation_source_path,
    flag_candidates,
    flag_source_path,
    model_candidates,
    model_source_path,
    plugin_candidates,
    plugin_source_path,
)
from sase.completion.candidates.catalog_content import (
    glossary_candidates,
    glossary_source_path,
    memory_candidates,
    memory_source_path,
)
from sase.completion.candidates.catalog_projects import (
    patch_candidates,
    patch_source_path,
    repo_candidates,
    repo_source_path,
    workspace_candidates,
    workspace_source_path,
)
from sase.completion.candidates.catalog_prompts import (
    skill_candidates,
    skill_source_path,
    tag_candidates,
    tag_source_path,
    xprompt_candidates,
    xprompt_source_path,
)
from sase.completion.candidates.catalog_sdd import (
    bead_candidates,
    bead_source_path,
    plan_candidates,
    plan_source_path,
)
from sase.completion.candidates.protocol import Candidate
from sase.completion.kinds import ValueKind

_Fetch = Callable[[str | None], list[Candidate]]
_SourcePath = Callable[[str | None], Path | None]

PROVIDERS: dict[ValueKind, tuple[_Fetch, _SourcePath]] = {
    ValueKind.BEAD: (bead_candidates, bead_source_path),
    ValueKind.REPO: (repo_candidates, repo_source_path),
    ValueKind.WORKSPACE: (workspace_candidates, workspace_source_path),
    ValueKind.FLAG: (flag_candidates, flag_source_path),
    ValueKind.GLOSSARY: (glossary_candidates, glossary_source_path),
    ValueKind.PLUGIN: (plugin_candidates, plugin_source_path),
    ValueKind.PLAN: (plan_candidates, plan_source_path),
    ValueKind.PATCH: (patch_candidates, patch_source_path),
    ValueKind.MEMORY: (memory_candidates, memory_source_path),
    ValueKind.XPROMPT: (xprompt_candidates, xprompt_source_path),
    ValueKind.SKILL: (skill_candidates, skill_source_path),
    ValueKind.PROC: (proc_candidates, proc_source_path),
    ValueKind.MONITOR: (monitor_candidates, monitor_source_path),
    ValueKind.ARTIFACT: (artifact_candidates, artifact_source_path),
    ValueKind.ARTIFACT_RELATION: (
        artifact_relation_candidates,
        artifact_relation_source_path,
    ),
    ValueKind.TAG: (tag_candidates, tag_source_path),
    ValueKind.AGENT: (agent_candidates, agent_source_path),
    ValueKind.MODEL: (model_candidates, model_source_path),
}


__all__ = ["PROVIDERS"]
