"""Update-skew auto-restart witness collection and corpus replay (read-only).

This package feeds the healer (a later phase): it collects the managed
code roots and the W1-W3 witnesses (boot identity drift, update journal,
file-level proof with the culprit commit), assembles classifier inputs
from ``done.json`` / ``agent_meta.json`` / runner logs, and enumerates
historical failures for ``sase agent auto-restart scan``.

Nothing here mutates agent state or the restart ledger: the scan path is
strictly read-only. The fresh-interpreter probe (W4) belongs to the
healer, so witnesses assembled here never carry a probe result.
"""

from __future__ import annotations
