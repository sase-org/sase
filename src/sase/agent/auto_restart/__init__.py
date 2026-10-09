"""Update-skew auto-restart: witnesses, corpus replay, and the healer.

Read-only surfaces (``managed_roots``, ``witnesses``, ``inputs``,
``history``) collect the managed code roots and the W1-W3 witnesses
(boot identity drift, update journal, file-level proof with the culprit
commit), assemble classifier inputs from ``done.json`` /
``agent_meta.json`` / runner logs, and enumerate historical failures for
``sase agent auto-restart scan``. The scan path never mutates agent
state or the restart ledger.

Mutating surfaces (``ledger``, ``quiescence``, ``probe``, ``storm``,
``healer``, ``notify``) implement ``sase agent auto-restart run``: the
healer claims the at-most-once ledger before any mutation, verifies the
signature, witnesses, quiescence, and the fresh-interpreter probe (W4),
then relaunches once per lineage through the provider-drain restart
seam. ``gate`` owns the flag-plus-config enablement check.
"""

from __future__ import annotations
