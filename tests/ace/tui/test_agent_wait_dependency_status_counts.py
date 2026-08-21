"""Tests for WAITING row dependency status-count projection."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text

from sase.ace.tui.agent_completion import (
    WaitAgentStatusCounts,
    WaitBeadStatusCounts,
    WaitDependencyStatusCounts,
    collect_agent_wait_status_maps,
    wait_dependency_status_counts,
)
from sase.ace.tui.models.agent_wait_beads import (
    WaitBeadStatusSnapshot,
    _WaitBeadStatusSnapshotEntry,
)
from sase.ace.tui.wait_status_presentation import (
    WAIT_DOMAIN_SEPARATOR,
    WAIT_UNKNOWN_GLYPH,
    WAIT_UNKNOWN_GLYPH_STYLE,
    format_wait_dependency_status_counts,
)
from sase.bead_status_presentation import (
    bead_status_display_order,
    bead_status_presentation,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent


def _dep(name: str, bucket: str):
    return make_agent(
        agent_name=name,
        raw_suffix=f"{name}-suffix",
        status="RUNNING",
        status_bucket=bucket,
    )


def _styles_covering(text: Text, substring: str) -> set[str]:
    start = text.plain.index(substring)
    end = start + len(substring)
    return {
        str(span.style) for span in text.spans if span.start < end and span.end > start
    }


def test_counts_keep_agent_and_bead_domains_separate() -> None:
    waiter = make_agent(
        status="WAITING",
        waiting_for=[
            "stopped",
            "failed",
            "starting",
            "running",
            "queued",
            "waiting",
            "done",
            "ghost",
        ],
        waiting_for_beads=[
            "open-bead",
            "claimed-bead",
            "ready-bead",
            "snoozed-bead",
            "running-bead",
            "done-bead",
            "bad-bead",
        ],
    )
    maps = collect_agent_wait_status_maps(
        [
            waiter,
            _dep("stopped", "Stopped"),
            _dep("failed", "Failed"),
            _dep("starting", "Starting"),
            _dep("running", "Running"),
            _dep("queued", "Queued"),
            _dep("waiting", "Waiting"),
            _dep("done", "Done"),
        ]
    )
    bead_snapshot = WaitBeadStatusSnapshot(
        (
            _WaitBeadStatusSnapshotEntry("open-bead", "open"),
            _WaitBeadStatusSnapshotEntry("claimed-bead", "claimed"),
            _WaitBeadStatusSnapshotEntry("ready-bead", "ready"),
            _WaitBeadStatusSnapshotEntry("snoozed-bead", "snoozed"),
            _WaitBeadStatusSnapshotEntry("running-bead", "in_progress"),
            _WaitBeadStatusSnapshotEntry("done-bead", "closed"),
            _WaitBeadStatusSnapshotEntry("bad-bead", "unsupported"),
        )
    )

    counts = wait_dependency_status_counts(waiter, maps, bead_snapshot)

    assert counts == WaitDependencyStatusCounts(
        agents=WaitAgentStatusCounts(
            stopped=1,
            failed=1,
            starting=1,
            running=1,
            queued=1,
            waiting=1,
            done=1,
            unknown=1,
        ),
        beads=WaitBeadStatusCounts(
            open=1,
            claimed=1,
            ready=1,
            snoozed=1,
            in_progress=1,
            closed=1,
            unknown=1,
        ),
    )
    rendered = format_wait_dependency_status_counts(counts)
    assert rendered.plain == ("▲1 ✗1 ◐1 ▶1 …1 ⏳1 ✓1 ?1 · ○1 ◎1 ◇1 ◈1 ◐1 ●1 ?1")
    assert "▶2" not in rendered.plain
    assert rendered.plain.index(WAIT_DOMAIN_SEPARATOR) < rendered.plain.rindex("?1")


def test_similar_agent_and_bead_statuses_do_not_merge() -> None:
    waiter = make_agent(
        status="WAITING",
        waiting_for=["starting"],
        waiting_for_beads=["running-bead"],
    )
    maps = collect_agent_wait_status_maps([waiter, _dep("starting", "Starting")])
    bead_snapshot = WaitBeadStatusSnapshot(
        (_WaitBeadStatusSnapshotEntry("running-bead", "in_progress"),)
    )

    counts = wait_dependency_status_counts(waiter, maps, bead_snapshot)
    rendered = format_wait_dependency_status_counts(counts)

    assert counts == WaitDependencyStatusCounts(
        agents=WaitAgentStatusCounts(starting=1),
        beads=WaitBeadStatusCounts(in_progress=1),
    )
    assert rendered.plain == "◐1 · ◐1"


def test_formatter_suppresses_zeroes_and_keeps_multi_digit_counts() -> None:
    counts = WaitDependencyStatusCounts(
        agents=WaitAgentStatusCounts(running=12, done=3, unknown=1)
    )

    rendered = format_wait_dependency_status_counts(counts)
    assert rendered.plain == "▶12 ✓3 ?1"
    assert "bold #FFD700" in _styles_covering(rendered, "▶12")
    assert "bold #5FD75F" in _styles_covering(rendered, "✓3")
    assert WAIT_UNKNOWN_GLYPH_STYLE in _styles_covering(rendered, "?1")


def test_formatter_emits_separator_only_for_mixed_domains() -> None:
    agent_only = format_wait_dependency_status_counts(
        WaitDependencyStatusCounts(agents=WaitAgentStatusCounts(running=2, done=1))
    )
    bead_only = format_wait_dependency_status_counts(
        WaitDependencyStatusCounts(
            beads=WaitBeadStatusCounts(open=2, in_progress=1),
        )
    )
    mixed = format_wait_dependency_status_counts(
        WaitDependencyStatusCounts(
            agents=WaitAgentStatusCounts(running=1),
            beads=WaitBeadStatusCounts(in_progress=2),
        )
    )
    unknown_mixed = format_wait_dependency_status_counts(
        WaitDependencyStatusCounts(
            agents=WaitAgentStatusCounts(unknown=1),
            beads=WaitBeadStatusCounts(unknown=2),
        )
    )

    assert agent_only.plain == "▶2 ✓1"
    assert WAIT_DOMAIN_SEPARATOR not in agent_only.plain
    assert bead_only.plain == "○2 ◐1"
    assert WAIT_DOMAIN_SEPARATOR not in bead_only.plain
    assert mixed.plain == "▶1 · ◐2"
    assert "dim" in _styles_covering(mixed, WAIT_DOMAIN_SEPARATOR)
    assert unknown_mixed.plain == "?1 · ?2"
    assert WAIT_UNKNOWN_GLYPH_STYLE in _styles_covering(unknown_mixed, "?1")
    assert WAIT_UNKNOWN_GLYPH_STYLE in _styles_covering(unknown_mixed, "?2")


def test_bead_tokens_use_canonical_glyph_color_and_unbroken_style() -> None:
    counts = WaitDependencyStatusCounts(
        beads=WaitBeadStatusCounts(
            open=1,
            claimed=1,
            ready=1,
            snoozed=1,
            in_progress=2,
            closed=1,
            unknown=3,
        )
    )
    rendered = format_wait_dependency_status_counts(counts)

    assert rendered.plain == "○1 ◎1 ◇1 ◈1 ◐2 ●1 ?3"
    assert "◆" not in rendered.plain
    for status in bead_status_display_order():
        presentation = bead_status_presentation(status)
        token = presentation.tui_glyph
        count = "2" if status == "in_progress" else "1"
        complete = f"{token}{count}"
        assert complete in rendered.plain
        covering = _styles_covering(rendered, complete)
        assert covering == {presentation.rich_style}
        assert token != WAIT_UNKNOWN_GLYPH
    assert _styles_covering(rendered, "?3") == {WAIT_UNKNOWN_GLYPH_STYLE}


def test_documented_wait_summary_examples_match_formatter() -> None:
    docs = Path("docs/ace.md").read_text(encoding="utf-8")
    mixed = format_wait_dependency_status_counts(
        WaitDependencyStatusCounts(
            agents=WaitAgentStatusCounts(running=1),
            beads=WaitBeadStatusCounts(in_progress=2),
        )
    )
    unknown_mixed = format_wait_dependency_status_counts(
        WaitDependencyStatusCounts(
            agents=WaitAgentStatusCounts(unknown=1),
            beads=WaitBeadStatusCounts(unknown=2),
        )
    )

    assert mixed.plain == "▶1 · ◐2"
    assert unknown_mixed.plain == "?1 · ?2"
    assert "WAITING ▶1 · ◐2" in docs
    assert "`?N`" in docs
    assert "trailing gold `◆` linked-bead badge" in docs


def test_cold_bead_cache_miss_is_omitted_until_warm() -> None:
    waiter = make_agent(status="WAITING", waiting_for_beads=["cold", "known"])
    maps = collect_agent_wait_status_maps([waiter])
    bead_snapshot = WaitBeadStatusSnapshot(
        (
            _WaitBeadStatusSnapshotEntry("cold", None, is_cold=True),
            _WaitBeadStatusSnapshotEntry("known", None),
        )
    )

    counts = wait_dependency_status_counts(waiter, maps, bead_snapshot)

    assert counts == WaitDependencyStatusCounts(beads=WaitBeadStatusCounts(unknown=1))
    assert format_wait_dependency_status_counts(counts).plain == "?1"


def test_stale_bead_status_stays_visible_during_revalidation() -> None:
    waiter = make_agent(status="WAITING", waiting_for_beads=["stale"])
    maps = collect_agent_wait_status_maps([waiter])
    bead_snapshot = WaitBeadStatusSnapshot(
        (_WaitBeadStatusSnapshotEntry("stale", "in_progress"),)
    )

    counts = wait_dependency_status_counts(waiter, maps, bead_snapshot)

    assert counts == WaitDependencyStatusCounts(
        beads=WaitBeadStatusCounts(in_progress=1)
    )
    assert format_wait_dependency_status_counts(counts).plain == "◐1"


def test_clan_wait_counts_expanded_members_not_aggregate() -> None:
    waiter = make_agent(status="WAITING", waiting_for=["clan"])
    container = make_agent(
        agent_name=None,
        raw_suffix="g",
        agent_clan="clan",
        agent_clan_generation="g",
        is_clan_container=True,
    )
    done = make_agent(
        agent_name="clan.done",
        raw_suffix="g-1",
        agent_clan="clan",
        agent_clan_generation="g",
        status="RUNNING",
        status_bucket="Done",
    )
    running = make_agent(
        agent_name="clan.running",
        raw_suffix="g-2",
        agent_clan="clan",
        agent_clan_generation="g",
        status="RUNNING",
        status_bucket="Running",
    )
    failed = make_agent(
        agent_name="clan.failed",
        raw_suffix="g-3",
        agent_clan="clan",
        agent_clan_generation="g",
        status="RUNNING",
        status_bucket="Failed",
    )
    container.runtime_children.extend([done, running, failed])
    maps = collect_agent_wait_status_maps([waiter, container, done, running, failed])

    counts = wait_dependency_status_counts(waiter, maps)

    assert counts == WaitDependencyStatusCounts(
        agents=WaitAgentStatusCounts(failed=1, running=1, done=1)
    )


def test_wait_display_source_owns_counted_dependencies() -> None:
    root = make_agent(status="WAITING", waiting_for=["root-dep"])
    child = make_agent(status="WAITING", waiting_for=["child-dep"])
    root.wait_display_source = child
    maps = collect_agent_wait_status_maps(
        [root, child, _dep("root-dep", "Failed"), _dep("child-dep", "Running")]
    )

    assert wait_dependency_status_counts(root, maps) == WaitDependencyStatusCounts(
        agents=WaitAgentStatusCounts(running=1)
    )


def test_tribe_time_and_runner_waits_do_not_enter_dependency_counts() -> None:
    waiter = make_agent(
        status="WAITING",
        waiting_for=["@default"],
        wait_duration=300,
        wait_runners=1,
        slot_requested_at="2026-07-12T12:00:00Z",
    )
    maps = collect_agent_wait_status_maps([waiter])

    assert wait_dependency_status_counts(waiter, maps) == WaitDependencyStatusCounts()


def test_bead_status_tokens_are_semantically_readable() -> None:
    unknown = WAIT_UNKNOWN_GLYPH
    rendered_unknown = format_wait_dependency_status_counts(
        WaitDependencyStatusCounts(beads=WaitBeadStatusCounts(unknown=1))
    )
    assert rendered_unknown.plain == "?1"
    for status in bead_status_display_order():
        presentation = bead_status_presentation(status)
        token = presentation.tui_glyph
        rendered = format_wait_dependency_status_counts(
            WaitDependencyStatusCounts(
                beads=WaitBeadStatusCounts(**{status: 1}),
            )
        )
        assert rendered.plain == f"{token}1"
        assert token != unknown
        assert _styles_covering(rendered, f"{token}1") == {presentation.rich_style}
