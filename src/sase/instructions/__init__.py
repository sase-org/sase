"""Observed instruction-load scoreboard for ``sase instructions verify``.

Pure parsers turn provider-owned session records into per-session
observations. The CLI handler and the doctor checks stay thin.
"""

from sase.instructions.fingerprints import (
    ACCEPTED_DECLARATION_OUTPUT,
    AGY_DIRECTIVE_MARKER,
    CLAUDE_DIRECTIVE_MARKER,
    CODEX_DIRECTIVE_MARKER,
    CONTRACT_HEADING,
    GROK_DIRECTIVE_OPENING,
    GUARD_DENY_REASON_PREFIX,
    HELPER_TEMPLATE_FIRST_LINE,
    MUSE_DIRECTIVE_MARKER,
)
from sase.instructions.models import ProviderRow, SessionObservation, VerifyReport

__all__ = [
    "ACCEPTED_DECLARATION_OUTPUT",
    "AGY_DIRECTIVE_MARKER",
    "CLAUDE_DIRECTIVE_MARKER",
    "CODEX_DIRECTIVE_MARKER",
    "CONTRACT_HEADING",
    "GROK_DIRECTIVE_OPENING",
    "GUARD_DENY_REASON_PREFIX",
    "HELPER_TEMPLATE_FIRST_LINE",
    "MUSE_DIRECTIVE_MARKER",
    "ProviderRow",
    "SessionObservation",
    "VerifyReport",
]
