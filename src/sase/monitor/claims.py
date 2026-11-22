"""Leaf module for the monitor workspace-claim workflow label.

Split out of :mod:`sase.monitor.start` so callers that only need the claim
label do not need a reason to reach for the monitor supervisor/CLI stack
(subprocess management, axe run-agent machinery, etc.) that
:mod:`sase.monitor.start` pulls in. The ``sase.monitor`` package resolves its
re-exports lazily, so importing this leaf does not load ``.start``.
"""

from __future__ import annotations

#: RUNNING-field workflow label used for a monitor's workspace claim, distinct
#: from ``"ace-run"`` so the starter's own runner-exit cleanup no longer
#: matches (and therefore cannot release) the claim once it is transferred.
MONITOR_WORKSPACE_CLAIM_WORKFLOW = "ace-monitor"

__all__ = ["MONITOR_WORKSPACE_CLAIM_WORKFLOW"]
