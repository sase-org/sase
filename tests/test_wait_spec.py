"""Unit tests for the shared approval/CLI wait-spec parser."""

from __future__ import annotations

import pytest

from sase.wait_spec import (
    WaitSpecError,
    format_wait_spec,
    parse_wait_spec,
    wait_spec_from_name_lists,
)
from sase.xprompt.directive_edit import PromptWaitDirective


def test_parse_agents_only() -> None:
    assert parse_wait_spec("sase-s7.2") == PromptWaitDirective(agents=("sase-s7.2",))
    assert parse_wait_spec("alice,bob") == PromptWaitDirective(agents=("alice", "bob"))


def test_parse_beads_only() -> None:
    assert parse_wait_spec("bead=sase-64.3") == PromptWaitDirective(
        beads=("sase-64.3",)
    )
    assert parse_wait_spec("bead=sase-1,bead=sase-2") == PromptWaitDirective(
        beads=("sase-1", "sase-2")
    )


def test_parse_hoods_only() -> None:
    assert parse_wait_spec("hood=sase-11l") == PromptWaitDirective(hoods=("sase-11l",))
    assert parse_wait_spec("hood=sase-1,hood=sase-2") == PromptWaitDirective(
        hoods=("sase-1", "sase-2")
    )


def test_parse_mixed_agents_beads_and_hoods() -> None:
    assert parse_wait_spec("sase-s7.2,bead=sase-64.3,hood=sase-11l") == (
        PromptWaitDirective(
            agents=("sase-s7.2",),
            beads=("sase-64.3",),
            hoods=("sase-11l",),
        )
    )
    assert parse_wait_spec(
        "bead=sase-64.3, alice ,hood=ship,bead=sase-1"
    ) == PromptWaitDirective(
        agents=("alice",),
        beads=("sase-64.3", "sase-1"),
        hoods=("ship",),
    )


def test_parse_mixed_agents_and_beads() -> None:
    assert parse_wait_spec("sase-s7.2,bead=sase-64.3") == PromptWaitDirective(
        agents=("sase-s7.2",),
        beads=("sase-64.3",),
    )
    assert parse_wait_spec("bead=sase-64.3, alice ,bead=sase-1") == PromptWaitDirective(
        agents=("alice",),
        beads=("sase-64.3", "sase-1"),
    )


def test_parse_strips_entry_whitespace_and_deduplicates() -> None:
    assert parse_wait_spec(
        " alice , alice ,bead=sase-1, bead=sase-1 ,hood=sase-11l, hood=sase-11l ,bob"
    ) == PromptWaitDirective(
        agents=("alice", "bob"),
        beads=("sase-1",),
        hoods=("sase-11l",),
    )


def test_format_round_trips_agents_then_beads_then_hoods() -> None:
    spec = parse_wait_spec("hood=sase-11l,bead=sase-1,alice,bead=sase-2,bob")
    assert format_wait_spec(spec) == "alice,bob,bead=sase-1,bead=sase-2,hood=sase-11l"
    assert parse_wait_spec(format_wait_spec(spec)) == spec


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("", "empty entry"),
        ("  ", "empty entry"),
        ("alice,,bob", "empty entry"),
        ("alice,", "empty entry"),
        (",alice", "empty entry"),
        ("alice bob", "whitespace-free"),
        ("bead=", "bead="),
        ("bead=sase 1", "bead="),
        ("hood=", "hood="),
        ("hood=sase 11l", "hood="),
        ("time=5m", "time="),
        ("runners=0", "runners="),
        ("priority=20", "priority="),
        ("unit=s", "unit="),
        ("proc=job", "proc="),
        ("foo=bar", "foo="),
        ("=foo", "leading '='"),
    ],
)
def test_parse_rejects_invalid_specs(text: str, match: str) -> None:
    with pytest.raises(WaitSpecError, match=match):
        parse_wait_spec(text)


def test_wait_spec_from_name_lists_rebuilds_and_rejects_malformed() -> None:
    assert wait_spec_from_name_lists(
        ["sase-s7.2"], ["sase-64.3"], ["sase-11l"]
    ) == PromptWaitDirective(
        agents=("sase-s7.2",),
        beads=("sase-64.3",),
        hoods=("sase-11l",),
    )
    assert wait_spec_from_name_lists([], []) is None
    assert wait_spec_from_name_lists("sase-s7.2", "sase-64.3") is None
    assert wait_spec_from_name_lists(["sase-s7.2"], [""]) == PromptWaitDirective(
        agents=("sase-s7.2",)
    )
    assert wait_spec_from_name_lists(["sase-s7.2"], None) == PromptWaitDirective(
        agents=("sase-s7.2",)
    )
