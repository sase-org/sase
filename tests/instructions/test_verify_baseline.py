"""Fixture-driven tests for the instruction scoreboard.

The synthetic corpus under ``tests/instructions/fixtures`` mirrors the real
provider shapes with no real transcript text. These tests reproduce the
baseline table from the epic plan and the expected after-state rows.
"""

from __future__ import annotations

import json
from pathlib import Path

from sase.instructions import agy as agy_parser
from sase.instructions import claude as claude_parser
from sase.instructions import codex as codex_parser
from sase.instructions import fingerprints as fp
from sase.instructions import grok as grok_parser
from sase.instructions import muse as muse_parser
from sase.instructions.models import SessionObservation
from sase.instructions.verify import aggregate_rows

FIXTURES = Path(__file__).parent / "fixtures"
HOME_H1 = "Synthetic Home"
PROJECT_H1 = "Synthetic Project"


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    with open(path, encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if line:
                decoded = json.loads(line)
                assert isinstance(decoded, dict)
                records.append(decoded)
    return records


def test_claude_baseline_root_row() -> None:
    """Claude roots load the contract twice with directive and auto-memory."""
    records = _read_jsonl(FIXTURES / "claude" / "root.jsonl")
    fields = claude_parser.observe_claude_session(
        records, home_h1=HOME_H1, project_h1=PROJECT_H1
    )
    assert fields["contract_count"] == 2
    assert fields["home"] is True
    assert fields["project"] is True
    assert fields["directive"] is True
    assert fields["native_full_count"] == 2
    assert fields["foreign"] == "auto-memory"


def test_claude_baseline_helpers() -> None:
    """A general-purpose helper attempts and accepts; Explore loads nothing."""
    gp_records = _read_jsonl(FIXTURES / "claude" / "helper_gp.jsonl")
    gp_files = claude_parser.instruction_files(gp_records)
    assert len(gp_files) == 2
    gp_signals = claude_parser.helper_signals(gp_records)
    assert gp_signals["attempts"] == 1
    assert gp_signals["accepted"] == 1

    explore_records = _read_jsonl(FIXTURES / "claude" / "helper_explore.jsonl")
    assert claude_parser.instruction_files(explore_records) == []
    explore_signals = claude_parser.helper_signals(explore_records)
    assert explore_signals["attempts"] == 0
    assert explore_signals["accepted"] == 0


def test_claude_after_state_helper() -> None:
    """After the stopgap, a helper carries the template plus a guard denial."""
    records = _read_jsonl(FIXTURES / "claude" / "helper_after.jsonl")
    signals = claude_parser.helper_signals(records)
    assert signals["has_template"] is True
    assert signals["attempts"] == 1
    assert signals["denied"] == 1


def test_codex_baseline_row() -> None:
    """Codex loads the contract twice with home, project, and directive."""
    records = _read_jsonl(FIXTURES / "codex" / "rollout.jsonl")
    fields = codex_parser.observe_codex_session(
        records, home_h1=HOME_H1, project_h1=PROJECT_H1
    )
    assert fields["contract_count"] == 2
    assert fields["home"] is True
    assert fields["project"] is True
    assert fields["directive"] is True
    assert fields["native_full_count"] == 2


def test_muse_baseline_row() -> None:
    """Muse loads the contract once with no home layer."""
    records = _read_jsonl(FIXTURES / "muse" / "session.jsonl")
    fields = muse_parser.observe_muse_session(
        records, home_h1=HOME_H1, project_h1=PROJECT_H1
    )
    assert fields["contract_count"] == 1
    assert fields["home"] is False
    assert fields["project"] is True
    assert fields["directive"] is True
    assert fields["native_full_count"] == 1


def test_grok_baseline_row() -> None:
    """Grok roots get nothing: no contract, home, project, or directive."""
    context = json.loads(
        (FIXTURES / "grok" / "prompt_context.json").read_text(encoding="utf-8")
    )
    system_prompt = (FIXTURES / "grok" / "system_prompt.txt").read_text(
        encoding="utf-8"
    )
    fields = grok_parser.observe_grok_session(
        context, system_prompt, project_h1=PROJECT_H1
    )
    assert fields["contract_count"] == 0
    assert fields["home"] is False
    assert fields["project"] is False
    assert fields["directive"] is False
    assert fields["native_full_count"] == 0


def test_grok_after_state_row() -> None:
    """After the stopgap, ``--rules`` carries the directive and project H1."""
    context = json.loads(
        (FIXTURES / "grok" / "prompt_context.json").read_text(encoding="utf-8")
    )
    system_prompt = (FIXTURES / "grok" / "system_prompt_after.txt").read_text(
        encoding="utf-8"
    )
    fields = grok_parser.observe_grok_session(
        context, system_prompt, project_h1=PROJECT_H1
    )
    assert fields["directive"] is True
    assert fields["project"] is True
    assert fields["native_full_count"] == 0


def test_agy_is_unverifiable_but_directive_observable() -> None:
    """agy reports directive presence only; every column else is unverifiable."""
    conversation = json.loads(
        (FIXTURES / "agy" / "conversation.json").read_text(encoding="utf-8")
    )
    fields = agy_parser.observe_agy_session(conversation)
    assert fields["directive"] is True
    assert fields["home"] is False
    assert fields["project"] is None


def test_baseline_table_aggregation() -> None:
    """Parser outputs aggregate to the plan's baseline table."""
    observations = [
        SessionObservation(
            provider="claude",
            run_name="synthetic",
            session_id="root",
            contract_count=2,
            home=True,
            project=True,
            directive=True,
            native_full_count=2,
            foreign="auto-memory",
        ),
        SessionObservation(
            provider="claude",
            run_name="synthetic",
            session_id="root/agent-gp",
            contract_count=2,
            helper_type="general-purpose",
            final_attempts=1,
            final_accepted=1,
        ),
        SessionObservation(
            provider="codex",
            run_name="synthetic",
            session_id="rollout",
            contract_count=2,
            home=True,
            project=True,
            directive=True,
            native_full_count=2,
        ),
        SessionObservation(
            provider="muse",
            run_name="synthetic",
            session_id="session",
            contract_count=1,
            home=False,
            project=True,
            directive=True,
            native_full_count=1,
        ),
        SessionObservation(
            provider="grok",
            run_name="synthetic",
            session_id="session",
            contract_count=0,
            home=False,
            project=False,
            directive=False,
            native_full_count=0,
            foreign="memory-v2½:False",
        ),
        SessionObservation(
            provider="agy",
            run_name="synthetic",
            session_id="conversation",
            contract_count=0,
            home=False,
            project=None,
            directive=True,
            native_full_count=0,
        ),
    ]
    rows = {row.provider: row for row in aggregate_rows(observations, [])}
    assert rows["claude"].contract == "2×"
    assert (rows["claude"].home, rows["claude"].project, rows["claude"].directive) == (
        "✓",
        "✓",
        "✓",
    )
    assert rows["claude"].native_full == "2×"
    assert rows["codex"].contract == "2×"
    assert rows["codex"].helpers == "0 spawns"
    assert rows["muse"].contract == "1×"
    assert rows["muse"].home == "✗"
    assert rows["grok"].contract == "0"
    assert rows["grok"].directive == "✗"
    assert rows["agy"].contract == "◌"
    assert rows["agy"].home == "✗"
    assert rows["agy"].project == "◌"
    assert rows["agy"].directive == "✓"
    assert rows["agy"].native_full == "◌"


def test_markers_match_shipped_directives() -> None:
    """Scoreboard fingerprints occur in the adapters' directive constants."""
    from sase.llm_provider import agy as agy_provider
    from sase.llm_provider import claude as claude_provider
    from sase.llm_provider import codex as codex_provider
    from sase.llm_provider import grok as grok_provider
    from sase.llm_provider._muse_directive import _muse_single_turn_directive

    assert fp.CLAUDE_DIRECTIVE_MARKER in claude_provider._SINGLE_TURN_DIRECTIVE
    assert fp.CODEX_DIRECTIVE_MARKER in codex_provider._codex_single_turn_directive()
    assert fp.MUSE_DIRECTIVE_MARKER in _muse_single_turn_directive(synchronous=True)
    assert fp.MUSE_DIRECTIVE_MARKER in _muse_single_turn_directive(synchronous=False)
    assert fp.AGY_DIRECTIVE_MARKER in agy_provider._AGY_PRINT_MODE_DIRECTIVE
    assert fp.GROK_DIRECTIVE_OPENING in grok_provider._GROK_SINGLE_TURN_DIRECTIVE
