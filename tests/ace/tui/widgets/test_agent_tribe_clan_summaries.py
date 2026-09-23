"""Digest, builder, and cache tests for tribe CLAN SUMMARIES."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.prompt_panel import (
    _agent_tribe_clan_summaries as clan_summaries,
)
from sase.ace.tui.widgets.prompt_panel._agent_tribe_aggregation import TribeUnitSource
from sase.ace.tui.widgets.prompt_panel._agent_tribe_clan_summaries import (
    _build_digest,
    _digest_for_summary,
    build_tribe_clan_summaries,
)

_NOW = datetime(2026, 7, 18, 16, 0, 0)

_EPIC_SUMMARY = """◆ EPIC demo-clan
Title: Rebuild the thing
Goal: first goal line
  second goal line
Counts: 1/2
"""

_WRAPPED_TITLE_SUMMARY = """◆ EPIC demo-clan
Title: Rebuild the thing
       across two lines
Goal: first goal line
"""

_CHOP_SUMMARY = """◆ TOOBIG SPLIT · 2 FILES
MISSION
Split the work across two files now.
"""

_LITERAL_SUMMARY = "Audit authentication and authorization"


def _agent(name: str, suffix: str, **overrides: object) -> Agent:
    values: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": name,
        "project_file": "/tmp/demo.sase",
        "status": "DONE",
        "start_time": _NOW,
        "stop_time": _NOW,
        "raw_suffix": suffix,
        "agent_name": name,
    }
    values.update(overrides)
    return Agent(**values)  # type: ignore[arg-type]


def _clan_root(
    name: str,
    summary: str | None,
    *,
    generation: str = "gen-1",
) -> Agent:
    return _agent(
        name,
        f"root-{name}",
        is_clan_container=True,
        agent_clan=name,
        agent_clan_generation=generation,
        clan_summary=summary,
    )


def _source(root: Agent, label: str) -> TribeUnitSource:
    return TribeUnitSource(
        root=root,
        unit_identity=root.identity,
        unit_label=label,
        rows=(root,),
        labels={root.identity: label},
    )


def test_epic_shape_yields_epic_kicker_title_headline_and_goal_lede() -> None:
    digest = _build_digest(_EPIC_SUMMARY, "demo-clan")

    assert digest.kicker == "EPIC"
    assert digest.headline == "Rebuild the thing"
    assert digest.lines[0] == "Title: Rebuild the thing"
    lede = digest.lines[digest.lede_start : digest.lede_start + digest.lede_count]
    assert lede[0] == "Goal: first goal line"


def test_wrapped_title_continuation_joins_at_value_column() -> None:
    digest = _build_digest(_WRAPPED_TITLE_SUMMARY, "demo-clan")

    assert digest.kicker == "EPIC"
    assert digest.headline == "Rebuild the thing across two lines"


def test_chop_shape_yields_split_kicker_and_mission_headline() -> None:
    digest = _build_digest(_CHOP_SUMMARY, "some-clan")

    assert digest.kicker == "TOOBIG SPLIT · 2 FILES"
    assert digest.headline == "Split the work across two files now."


def test_research_shape_takes_label_kicker_and_truncated_headline() -> None:
    raw = "RESEARCH PROMPT: " + "word " * 40
    digest = _build_digest(raw, "some-clan")

    assert digest.kicker == "RESEARCH PROMPT"
    assert len(digest.headline) <= 120
    assert digest.headline.endswith("…")
    # A truncated headline replays its own block as the lede.
    assert (digest.lede_start, digest.lede_count) == (0, 1)


def test_truncated_paragraph_lede_stays_capped_at_four_lines() -> None:
    paragraph = "\n".join(
        f"line {index} of a long mission paragraph" for index in range(12)
    )
    digest = _build_digest(f"◆ TOOBIG SPLIT · 2 FILES\nMISSION\n{paragraph}\n", "c")

    assert digest.headline.endswith("…")
    # The lede starts at the paragraph (past the MISSION label), capped at 4 lines.
    assert (digest.lede_start, digest.lede_count) == (1, 4)
    assert digest.lines[digest.lede_start] == "line 0 of a long mission paragraph"


def test_literal_shape_has_no_kicker() -> None:
    digest = _build_digest(_LITERAL_SUMMARY, "some-clan")

    assert digest.kicker == ""
    assert digest.headline == _LITERAL_SUMMARY


def test_invalid_markup_falls_back_to_plain_text() -> None:
    digest = _build_digest("see [@file:x] for details", "some-clan")

    assert digest.headline == "see [@file:x] for details"
    assert digest.lines == ("see [@file:x] for details",)


def test_banner_only_summary_uses_kicker_as_headline() -> None:
    digest = _build_digest("◆ EPIC demo-clan", "demo-clan")

    assert digest.kicker == ""
    assert digest.headline == "EPIC"
    assert digest.lines == ()


def test_blank_summary_digest_is_safe() -> None:
    digest = _digest_for_summary("", "blank-clan-xyz")

    assert digest.headline == ""
    assert digest.kicker == ""


def test_owner_qualified_clan_token_stripped_from_kicker() -> None:
    digest = _build_digest(
        "◆ EPIC owner/demo-clan\nTitle: Something here\n", "demo-clan"
    )

    assert digest.kicker == "EPIC"
    assert digest.headline == "Something here"


def test_digest_key_is_stable_12_hex() -> None:
    first = _build_digest(_EPIC_SUMMARY, "demo-clan")
    second = _build_digest(_EPIC_SUMMARY, "demo-clan")

    assert len(first.key) == 12
    assert first.key == second.key
    assert _build_digest(_EPIC_SUMMARY, "other-clan").key != first.key


def test_builder_skips_blank_and_non_clan_units_in_roster_order() -> None:
    clan = _clan_root("demo-clan", _EPIC_SUMMARY)
    blank = _clan_root("blank", "  \n ")
    plain = _agent("solo", "solo-1")
    literal = _clan_root("beta", _LITERAL_SUMMARY)
    snapshot = build_tribe_clan_summaries(
        (
            _source(clan, "alpha"),
            _source(blank, "blank"),
            _source(plain, "solo"),
            _source(literal, "beta"),
        )
    )

    assert [entry.unit_label for entry in snapshot.entries] == ["alpha", "beta"]
    assert snapshot.entries[0].digest.kicker == "EPIC"
    assert snapshot.entries[1].digest.headline == _LITERAL_SUMMARY


def test_entry_key_is_stable_per_clan_generation() -> None:
    first = build_tribe_clan_summaries((_source(_clan_root("alpha", "one"), "alpha"),))
    second = build_tribe_clan_summaries((_source(_clan_root("alpha", "two"), "alpha"),))
    other_gen = build_tribe_clan_summaries(
        (_source(_clan_root("alpha", "one", generation="gen-2"), "alpha"),)
    )

    assert len(first.entries[0].entry_key) == 12
    assert first.entries[0].entry_key == second.entries[0].entry_key
    assert first.entries[0].entry_key != other_gen.entries[0].entry_key


def test_cache_hit_avoids_reparsing(monkeypatch: Any) -> None:
    calls = 0
    original = clan_summaries.clan_summary_markup_text

    def counted(raw: str) -> Any:
        nonlocal calls
        calls += 1
        return original(raw)

    monkeypatch.setattr(clan_summaries, "clan_summary_markup_text", counted)
    raw = "Cache probe summary one.\nSecond line.\n"

    _digest_for_summary(raw, "cache-clan-xyz")
    first_calls = calls
    assert first_calls > 0
    _digest_for_summary(raw, "cache-clan-xyz")

    assert calls == first_calls
    _digest_for_summary(raw, "other-cache-clan-xyz")
    assert calls > first_calls
