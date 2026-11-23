"""Gather stranded-work facts for the sase-core reducer.

Python owns process liveness, marker files, and the small JSON reads the
host already performs. The scan is cheap (one batched index query per
hundred candidate sessions, one JSON read per candidate) and ignores ACE
dismissal so flags survive hiding a row. Open beads that carry an active
completion failure are recovery candidates; their failure provenance names
the run to load without changing the bead assignee. An adopted staged
handoff whose successor has been delivered no longer owns the bead; the
successor owns it through its own session member when live.

Compatibility facade: the collector lives in focused modules; this module
keeps the historical ``sase.bead.stranded_facts`` import surface intact.
Patch the module that defines a helper (``_stranded_facts_snapshot``,
``_stranded_facts_members``, ...), not this facade.
"""

from __future__ import annotations

from sase.bead._stranded_facts_collect import (
    collect_issue_titles,
    collect_stranded_work_input,
    collect_stranded_work_snapshot,
)

__all__ = [
    "collect_issue_titles",
    "collect_stranded_work_input",
    "collect_stranded_work_snapshot",
]
