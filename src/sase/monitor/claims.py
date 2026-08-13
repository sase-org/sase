"""Leaf module for the monitor workspace-claim workflow label.

Split out of :mod:`sase.monitor.start` so callers that only need the claim
label do not need a reason to reach for the monitor supervisor/CLI stack
(subprocess management, axe run-agent machinery, etc.) that
:mod:`sase.monitor.start` pulls in. Importing any submodule of the
``sase.monitor`` package still runs ``sase/monitor/__init__.py``, which
imports ``.start`` eagerly, so callers on a hot path (the TUI agent loader)
should still import this module lazily, inside the function that needs it —
the same convention already used elsewhere in the code for this constant.
"""

from __future__ import annotations

#: RUNNING-field workflow label used for a monitor's workspace claim, distinct
#: from ``"ace-run"`` so the starter's own runner-exit cleanup no longer
#: matches (and therefore cannot release) the claim once it is transferred.
MONITOR_WORKSPACE_CLAIM_WORKFLOW = "ace-monitor"

__all__ = ["MONITOR_WORKSPACE_CLAIM_WORKFLOW"]
