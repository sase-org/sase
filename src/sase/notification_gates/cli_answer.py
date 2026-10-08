"""``sase gate answer`` -- answer a durable gate headlessly.

Facade preserving the original module's public import path. The
implementation lives in the ``cli_answer_*`` sibling modules; this module
re-exports their public names and nothing ``_``-private.
"""

from __future__ import annotations

from sase.notification_gates.cli_answer_handle import (
    handle_gate_answer as handle_gate_answer,
)
from sase.notification_gates.cli_answer_submit import (
    GATE_ANSWER_DETACH_ORIGIN as GATE_ANSWER_DETACH_ORIGIN,
)

__all__ = ["GATE_ANSWER_DETACH_ORIGIN", "handle_gate_answer"]
