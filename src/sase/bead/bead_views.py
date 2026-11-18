"""Legacy machine-local log of agent ``sase bead show`` views.

Agents are refused at ``show`` and told to run ``sase bead read`` instead,
so ``bead_views.jsonl`` is no longer written. The targeted view query in
:mod:`sase.core.bead_touch_index_query` folds this log in Rust for display;
this module keeps only the log-path helper shared by that query's callers.

``SASE_BEAD_SKIP_VIEW_LOG=1`` marks automation that runs inside an agent
(symvision, flag checks, commit hooks), whose ``show`` probes neither count
as agent consultations nor trip the agent guard.

Limitation: this log is machine-local. A remote agent's views are not
visible on this machine while its mutations (which sync through the bead
store) are, so ``viewed`` is always a lower bound.
"""

from __future__ import annotations

from pathlib import Path

from sase.core.paths import sase_projects_dir
from sase.main.init_memory.config import project_memory_name
from sase.project_aliases import resolve_project_alias_ref

BEAD_VIEWS_FILENAME = "bead_views.jsonl"
# Marks automation that runs inside an agent, whose ``show`` probes neither
# count as agent consultations nor trip the agent guard.
SASE_BEAD_SKIP_VIEW_LOG = "SASE_BEAD_SKIP_VIEW_LOG"


def bead_views_log_path(project: str | None = None, *, cwd: Path | None = None) -> Path:
    """Return ``~/.sase/projects/<key>/bead_views.jsonl``."""

    project_name = resolve_project_alias_ref(
        project or project_memory_name(cwd or Path.cwd())
    )
    return sase_projects_dir() / project_name / BEAD_VIEWS_FILENAME


__all__ = [
    "BEAD_VIEWS_FILENAME",
    "SASE_BEAD_SKIP_VIEW_LOG",
    "bead_views_log_path",
]
