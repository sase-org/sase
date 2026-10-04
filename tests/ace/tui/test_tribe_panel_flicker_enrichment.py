"""Tribe panel flicker: disk snapshots and enrichment dedup."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from textual.worker import WorkerState

from sase.ace.tui.models.agent_tribe_summary import build_agent_tribe_summary_snapshot
from tests.ace.tui._tribe_panel_flicker_helpers import (
    FLICKER_NOW,
    make_tribe_flicker_agent,
)


def test_signature_change_retains_disk_and_requests_refresh() -> None:
    from sase.ace.tui.widgets.prompt_panel._agent_tribe_aggregation import (
        _TribeDiskSnapshot,
        cache_tribe_enrichment,
        get_cached_tribe_section_snapshot,
        prepare_tribe_section_snapshot,
        tribe_sections_to_refresh,
        TribeEnrichmentResult,
    )

    first = make_tribe_flicker_agent("first", "first")
    summary = build_agent_tribe_summary_snapshot(
        "epic", [first], panel_collapsed=True, now=FLICKER_NOW
    )
    widget = SimpleNamespace()
    prepare_tribe_section_snapshot(widget, summary, [first])
    sources_before = cast(
        Any,
        __import__(
            "sase.ace.tui.widgets.prompt_panel._agent_tribe_aggregation",
            fromlist=["get_cached_tribe_sources"],
        ).get_cached_tribe_sources(widget, summary.container_identity),
    )
    disk = _TribeDiskSnapshot(
        loaded_sections=frozenset({"replies", "prompts", "slow-tool-calls"}),
        replies=(),
        slow_tool_calls=(),
    )
    result = TribeEnrichmentResult(
        panel_identity=summary.container_identity,
        source_signature=tuple(
            cast(Any, source).signature for source in sources_before
        ),
        disk=disk,
        runtime_statistics_refreshed=False,
        runtime_statistics=None,
    )
    assert cache_tribe_enrichment(widget, result) is not None

    second = make_tribe_flicker_agent("second", "second")
    changed_summary = build_agent_tribe_summary_snapshot(
        "epic", [first, second], panel_collapsed=True, now=FLICKER_NOW
    )
    assert changed_summary.container_identity == summary.container_identity
    retained = prepare_tribe_section_snapshot(widget, changed_summary, [first, second])
    assert retained.disk is disk
    assert retained.loading_sections == frozenset()
    refresh = tribe_sections_to_refresh(
        widget, summary.container_identity, {"replies", "prompts", "slow-tool-calls"}
    )
    assert refresh == frozenset({"replies", "prompts", "slow-tool-calls"})
    cached = get_cached_tribe_section_snapshot(widget, summary.container_identity)
    assert cached is not None and cached.disk is disk


def test_departed_units_are_filtered_from_disk_sections() -> None:
    from rich.text import Text

    from sase.ace.tui.models._agent_clan_sections import (
        ClanDiskMemberSnapshot,
        ClanTextEntry,
    )
    from sase.ace.tui.widgets.prompt_panel._agent_display_tribe_prompts import (
        append_prompts,
    )
    from sase.ace.tui.widgets.prompt_panel._agent_display_tribe_sections import (
        append_replies,
        append_slow_tool_calls,
    )
    from sase.ace.tui.widgets.prompt_panel._agent_tribe_aggregation import (
        _TribeDiskSnapshot,
        TribeSectionSnapshot,
        TribeSlowToolEntry,
        TribeTextEntry,
    )
    from sase.ace.tui.widgets.prompt_panel._agent_tribe_prompts import (
        TribePromptGroup,
        TribePromptMember,
        TribePromptsSnapshot,
    )
    from sase.ace.tui.models.fold_state import FoldLevel

    present: set[Any] = {("running", "keep", None)}
    departed: Any = ("running", "departed", None)
    reply_entry = TribeTextEntry(
        unit_identity=departed,
        unit_label="departed",
        entry=ClanTextEntry(
            member_identity=departed,
            member_label="departed",
            kind="REPLY",
            preview="hi",
            body="hi",
        ),
    )
    kept_reply = TribeTextEntry(
        unit_identity=("running", "keep", None),
        unit_label="keep",
        entry=ClanTextEntry(
            member_identity=("running", "keep", None),
            member_label="keep",
            kind="REPLY",
            preview="kept",
            body="kept",
        ),
    )
    snapshot = TribeSectionSnapshot(
        panel_identity=("panel", "epic"),
        source_signature=(),
        disk=_TribeDiskSnapshot(
            loaded_sections=frozenset({"replies", "slow-tool-calls", "prompts"}),
            replies=(reply_entry, kept_reply),
            slow_tool_calls=(
                TribeSlowToolEntry(
                    unit_identity=departed,
                    unit_label="departed",
                    entry=cast(
                        Any,
                        SimpleNamespace(
                            member_label="departed",
                            call=SimpleNamespace(
                                entry=SimpleNamespace(
                                    display_tool_name="tool",
                                    compact_target="",
                                    detail="",
                                ),
                                effective_duration_ms=1000,
                                is_running=False,
                                did_not_complete=False,
                            ),
                        ),
                    ),
                ),
            ),
            prompts=TribePromptsSnapshot(
                groups=(
                    TribePromptGroup(
                        digest=cast(
                            Any,
                            SimpleNamespace(
                                group_key="g1",
                                headline="departed headline",
                                headline_spans=(),
                                body="departed body",
                                body_spans=(),
                                body_line_count=1,
                                launch="",
                                launch_spans=(),
                                macros=(),
                                project=None,
                            ),
                        ),
                        members=(
                            TribePromptMember(
                                unit_identity=departed,
                                unit_label="departed",
                                member_identity=departed,
                                member_label="departed",
                            ),
                        ),
                    ),
                    TribePromptGroup(
                        digest=cast(
                            Any,
                            SimpleNamespace(
                                group_key="g2",
                                headline="kept headline",
                                headline_spans=(),
                                body="kept body",
                                body_spans=(),
                                body_line_count=1,
                                launch="",
                                launch_spans=(),
                                macros=(),
                                project=None,
                            ),
                        ),
                        members=(
                            TribePromptMember(
                                unit_identity=("running", "keep", None),
                                unit_label="keep",
                                member_identity=("running", "keep", None),
                                member_label="keep",
                            ),
                        ),
                    ),
                ),
                agent_count=2,
                multi_project=False,
            ),
        ),
    )
    text = Text()
    append_replies(text, snapshot, level=FoldLevel.EXHAUSTIVE, present_units=present)
    assert "departed" not in text.plain
    assert "kept" in text.plain

    slow_text = Text()
    append_slow_tool_calls(
        slow_text, snapshot, level=FoldLevel.EXHAUSTIVE, present_units=present
    )
    assert slow_text.plain == ""

    prompt_text = Text()
    append_prompts(
        prompt_text,
        snapshot,
        level=FoldLevel.COLLAPSED,
        overrides={},
        unit_numbers={},
        present_units=present,
    )
    assert "departed headline" not in prompt_text.plain
    assert "kept headline" in prompt_text.plain


def test_identical_enrichment_result_posts_no_message() -> None:
    from sase.ace.tui.widgets.prompt_panel._agent_display_async_groups import (
        AgentDisplayGroupWorkerMixin,
    )
    from sase.ace.tui.widgets.prompt_panel._agent_tribe_aggregation import (
        _TribeDiskSnapshot,
        cache_tribe_enrichment,
        prepare_tribe_section_snapshot,
        TribeEnrichmentResult,
    )
    from sase.ace.tui.widgets.prompt_panel._agent_tribe_clan_summaries import (
        TribeClanSummariesSnapshot,
    )

    first = make_tribe_flicker_agent("first", "first")
    summary = build_agent_tribe_summary_snapshot(
        "epic", [first], panel_collapsed=True, now=FLICKER_NOW
    )

    class _Panel(AgentDisplayGroupWorkerMixin):
        def __init__(self) -> None:
            self.messages: list[Any] = []
            self._tribe_section_pending_request = None

        def post_message(self, message: Any) -> None:
            self.messages.append(message)

    panel = _Panel()
    prepare_tribe_section_snapshot(panel, summary, [first])
    from sase.ace.tui.widgets.prompt_panel._agent_tribe_aggregation import (
        get_cached_tribe_sources,
    )

    sources = get_cached_tribe_sources(panel, summary.container_identity)
    signature = tuple(cast(Any, source).signature for source in sources)
    disk = _TribeDiskSnapshot(
        loaded_sections=frozenset({"replies"}),
        replies=(),
        slow_tool_calls=(),
    )
    clan_summaries = TribeClanSummariesSnapshot(entries=(), signature=())
    first_result = TribeEnrichmentResult(
        panel_identity=summary.container_identity,
        source_signature=signature,
        disk=disk,
        runtime_statistics_refreshed=True,
        runtime_statistics=None,
        clan_summaries=clan_summaries,
    )
    assert cache_tribe_enrichment(panel, first_result) is not None

    worker = SimpleNamespace(
        result=TribeEnrichmentResult(
            panel_identity=summary.container_identity,
            source_signature=signature,
            disk=disk,
            runtime_statistics_refreshed=False,
            runtime_statistics=None,
            clan_summaries=clan_summaries,
        )
    )
    panel._tribe_section_worker = worker  # type: ignore[attr-defined]
    panel._tribe_section_request = SimpleNamespace(  # type: ignore[attr-defined]
        panel_identity=summary.container_identity, sections=frozenset()
    )
    panel._apply_tribe_section_enrichment_result(worker, WorkerState.SUCCESS)  # type: ignore[arg-type]
    assert panel.messages == []

    changed_disk = _TribeDiskSnapshot(
        loaded_sections=frozenset({"replies", "prompts"}),
        replies=(),
        slow_tool_calls=(),
    )
    worker2 = SimpleNamespace(
        result=TribeEnrichmentResult(
            panel_identity=summary.container_identity,
            source_signature=signature,
            disk=changed_disk,
            runtime_statistics_refreshed=False,
            runtime_statistics=None,
            clan_summaries=clan_summaries,
        )
    )
    panel._tribe_section_worker = worker2  # type: ignore[attr-defined]
    panel._tribe_section_request = SimpleNamespace(  # type: ignore[attr-defined]
        panel_identity=summary.container_identity, sections=frozenset()
    )
    panel._apply_tribe_section_enrichment_result(worker2, WorkerState.SUCCESS)  # type: ignore[arg-type]
    assert len(panel.messages) == 1
