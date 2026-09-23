"""Shared wait-signal detection for provider stranded-wait guards."""

from __future__ import annotations

import re

#: Matches reply tails that claim the turn is waiting on something external:
#: a background notification, a wake-up, or a still-running command. Shared by
#: the Claude and Muse wait guards so both providers classify wait claims the
#: same way.
WAIT_SIGNAL_RE = re.compile(
    r"\b(?:"
    r"i(?:'|\u2019)ll wait|"
    r"will be notified|"
    r"notify me|"
    r"when (?:it|the command|the task|the process) "
    r"(?:completes?|finishes?)|"
    r"waiting for|"
    r"still running|"
    r"in the background"
    r")\b",
    re.IGNORECASE,
)


def ends_with_wait_claim(text: str, tail_chars: int = 700) -> bool:
    """Return whether the tail of *text* reads like a wait claim."""
    return bool(WAIT_SIGNAL_RE.search(text.strip()[-tail_chars:]))
