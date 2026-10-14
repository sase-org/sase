"""Shared literal markers and fingerprint helpers.

Phase workers must use these exact strings (epic plan decision 5). Tests tie
the scoreboard fingerprints to the shipped adapter constants.
"""

from __future__ import annotations

import re

# Heading text of the contract section in memory-sase.template.md.
CONTRACT_HEADING = "SASE Final Declaration"
# Opening of the Grok single-turn directive (owned by grok-root).
GROK_DIRECTIVE_OPENING = "SASE single-turn instructions for Grok:"
# First line of the packaged Claude helper template (owned by claude-helpers).
HELPER_TEMPLATE_FIRST_LINE = "# SASE Helper Instructions"
# Prefix of the PreToolUse guard deny reason (owned by claude-helpers).
GUARD_DENY_REASON_PREFIX = "SASE helper guard:"
# Stdout fragment of an accepted ``sase final submit``.
ACCEPTED_DECLARATION_OUTPUT = "Accepted final declaration"

# Existing per-provider directive markers.
CLAUDE_DIRECTIVE_MARKER = "SASE single-turn print mode"
CODEX_DIRECTIVE_MARKER = "SASE single-turn instructions for Codex"
MUSE_DIRECTIVE_MARKER = "SASE single-turn instructions for Muse Code"
AGY_DIRECTIVE_MARKER = "SASE Antigravity print-mode instructions"

# A helper's attempt at a root-only ``sase final`` operation: a Bash tool_use
# whose command matches this, or a Skill tool_use of ``sase_final``.
FINAL_ATTEMPT_RE = re.compile(r"\bsase\s+final\s+(context|defer|prepare|submit)\b")

# Root-only skills denied to native helpers (owned by claude-helpers).
ROOT_ONLY_SKILLS: tuple[str, ...] = (
    "sase_final",
    "sase_gate",
    "sase_git_commit",
    "sase_handoff",
    "sase_monitor",
    "sase_plan",
    "sase_questions",
    "sase_run",
    "sase_sudo",
)

# Marker syntax is shared with ``llm_provider.instruction_delivery``. Keep
# the matcher permissive about the UUID payload so archived manifests remain
# readable if the invocation id representation ever changes.
BUNDLE_MARKER_RE = re.compile(
    r"<!--\s*sase-instructions\s+bundle=([0-9a-f]{12})\s+"
    r"invocation=([^\s>]+)\s*-->"
)
CLAUDE_AUTO_MEMORY_HEADING = "# Memory"
CLAUDE_AUTO_MEMORY_LEAD_IN = "You have a persistent file-based memory at"
_CONTRACT_HEADING_RE = re.compile(r"(?m)^#{1,6}[ \t]+SASE Final Declaration[ \t]*$")


def flatten_ws(text: str) -> str:
    """Collapse all whitespace runs to single spaces."""
    return re.sub(r"\s+", " ", text)


def count_occurrences(needle: str, text: str) -> int:
    """Count non-overlapping occurrences after whitespace normalization."""
    flattened_needle = flatten_ws(needle).strip()
    if not flattened_needle:
        return 0
    return flatten_ws(text).count(flattened_needle)


def count_contract_occurrences(texts: list[str]) -> int:
    """Count every visible contract-heading occurrence in loaded sources."""
    return sum(len(_CONTRACT_HEADING_RE.findall(text)) for text in texts)


def contains_heading(text: str, expected_h1: str | None) -> bool:
    """Return whether *text* contains an H1 with the expected title."""
    if not text or expected_h1 is None:
        return False
    return any(line.strip() == f"# {expected_h1}" for line in text.splitlines())


def bundle_markers(texts: list[str]) -> tuple[tuple[str, str], ...]:
    """Return bundle marker ``(sha12, invocation_id)`` pairs in source order."""
    return tuple(
        (match.group(1), match.group(2))
        for text in texts
        for match in BUNDLE_MARKER_RE.finditer(text)
    )


def count_bundle_markers(
    markers: tuple[tuple[str, str], ...],
    invocation_id: str,
    *,
    bundle_sha256: str | None = None,
) -> int:
    """Count markers for an invocation, optionally requiring its bundle sha."""
    expected_sha = bundle_sha256[:12] if bundle_sha256 else None
    return sum(
        1
        for sha, invocation in markers
        if invocation == invocation_id and (expected_sha is None or sha == expected_sha)
    )


def has_claude_auto_memory(snapshot: str) -> bool:
    """Match the exact Claude auto-memory fingerprint recorded by the E3 spike."""
    lines = snapshot.splitlines()
    return any(
        line.strip() == CLAUDE_AUTO_MEMORY_HEADING
        and CLAUDE_AUTO_MEMORY_LEAD_IN in "\n".join(lines[index + 1 : index + 5])
        for index, line in enumerate(lines)
    )


def first_h1(text: str) -> str | None:
    """Return the first Markdown H1 of *text*, or ``None``."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip() or None
    return None


def matches_h1(text: str, expected_h1: str | None) -> bool | None:
    """Match the first H1 of *text* against *expected_h1*.

    Returns ``None`` when either side is unknown (unverifiable).
    """
    if not text or expected_h1 is None:
        return None
    actual = first_h1(text)
    if actual is None:
        return False
    return actual == expected_h1


__all__ = [
    "ACCEPTED_DECLARATION_OUTPUT",
    "AGY_DIRECTIVE_MARKER",
    "BUNDLE_MARKER_RE",
    "CLAUDE_DIRECTIVE_MARKER",
    "CODEX_DIRECTIVE_MARKER",
    "CONTRACT_HEADING",
    "FINAL_ATTEMPT_RE",
    "GROK_DIRECTIVE_OPENING",
    "GUARD_DENY_REASON_PREFIX",
    "HELPER_TEMPLATE_FIRST_LINE",
    "CLAUDE_AUTO_MEMORY_HEADING",
    "CLAUDE_AUTO_MEMORY_LEAD_IN",
    "MUSE_DIRECTIVE_MARKER",
    "ROOT_ONLY_SKILLS",
    "contains_heading",
    "bundle_markers",
    "count_bundle_markers",
    "count_contract_occurrences",
    "count_occurrences",
    "has_claude_auto_memory",
    "first_h1",
    "flatten_ws",
    "matches_h1",
]
