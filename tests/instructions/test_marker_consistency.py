"""Marker-consistency tests tying scoreboard fingerprints to shipped constants.

Epic plan E1 decision 5: the ``record`` phase owns cross-checks proving the
scoreboard's Grok directive marker, helper template marker, and guard marker
equal what ``grok-root`` and ``claude-helpers`` shipped. (The per-provider
directive cross-checks live in ``test_verify_baseline.py``.)
"""

from __future__ import annotations

from importlib import resources

from sase.instructions import fingerprints as fp
from sase.llm_provider import _claude_helper_channel as helper_channel
from sase.llm_provider import _claude_helper_guard as helper_guard
from sase.llm_provider import grok as grok_provider


def test_grok_directive_opens_with_fingerprint() -> None:
    """The shipped Grok directive starts with the scoreboard's opening marker."""
    assert grok_provider._GROK_SINGLE_TURN_DIRECTIVE.startswith(
        fp.GROK_DIRECTIVE_OPENING
    )


def test_helper_template_first_line_matches_fingerprint() -> None:
    """The packaged helper template's first line is the fingerprinted marker."""
    template_path = helper_channel.helper_template_path()
    first_line = template_path.read_text(encoding="utf-8").splitlines()[0]
    assert first_line == fp.HELPER_TEMPLATE_FIRST_LINE
    assert first_line == helper_channel.HELPER_TEMPLATE_FIRST_LINE


def test_guard_deny_prefix_matches_fingerprint() -> None:
    """The shipped guard's deny-reason prefix is the fingerprinted marker."""
    assert helper_guard.GUARD_DENY_REASON_PREFIX == fp.GUARD_DENY_REASON_PREFIX


def test_root_only_skills_match_fingerprint() -> None:
    """The guard and the scoreboard agree on the root-only skill list."""
    assert frozenset(fp.ROOT_ONLY_SKILLS) == helper_guard.ROOT_ONLY_SKILLS


def test_contract_heading_in_shipped_template() -> None:
    """The scoreboard's contract heading is the shipped template's section."""
    template_text = (
        resources.files("sase.main.init_memory")
        .joinpath("templates/memory-sase.template.md")
        .read_text(encoding="utf-8")
    )
    assert fp.CONTRACT_HEADING in template_text
