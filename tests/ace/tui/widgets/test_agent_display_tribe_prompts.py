"""Renderer tests for the tribe PROMPTS section."""

from __future__ import annotations

from typing import Any

from rich.text import Text

from sase.ace.tui.models.agent_tribe_summary import build_agent_tribe_summary_snapshot
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_display_tribe import (
    build_tribe_detail_text,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_tribe_prompts import (
    append_prompts,
)
from sase.ace.tui.widgets.prompt_panel._agent_tribe_aggregation import (
    TribeSectionSnapshot,
    _TribeDiskSnapshot,
)
from sase.ace.tui.widgets.prompt_panel._agent_tribe_clan_summaries import (
    empty_tribe_clan_summaries_snapshot,
)
from sase.ace.tui.widgets.prompt_panel._agent_tribe_prompts import (
    PromptDigest,
    TribePromptGroup,
    TribePromptMember,
    TribePromptsSnapshot,
    _digest_project,
)
from sase.ace.tui.widgets.prompt_panel._section_navigation import (
    SECTION_FOLD_ONLY_META_KEY,
    SECTION_MARKER_META_KEY,
)

from tests.ace.tui.widgets._agent_display_tribe_helpers import (
    NOW,
    make_tribe_agent,
    make_tribe_snapshot,
)


def _digest(
    headline: str,
    *,
    key: str = "abc123",
    body: str = "Body line.\n",
    launch: str = "",
    chips: tuple[str, ...] = (),
    project: str | None = None,
) -> PromptDigest:
    stripped = body.strip()
    lines = stripped.count("\n") + 1 if stripped else 0
    return PromptDigest(
        group_key=key,
        headline=headline,
        headline_spans=(),
        body=stripped,
        body_spans=(),
        body_line_count=lines,
        launch=launch,
        launch_spans=(),
        xprompts=chips,
        project=project,
    )


def _member(
    unit_identity: Any,
    unit_label: str,
    member_identity: Any = None,
    member_label: str | None = None,
) -> TribePromptMember:
    identity = member_identity if member_identity is not None else unit_identity
    return TribePromptMember(
        unit_identity=unit_identity,
        unit_label=unit_label,
        member_identity=identity,
        member_label=member_label if member_label is not None else unit_label,
    )


def _prompts_snapshot(
    groups: tuple[TribePromptGroup, ...],
    *,
    multi_project: bool = False,
) -> TribePromptsSnapshot:
    return TribePromptsSnapshot(
        groups=groups,
        agent_count=sum(len(group.members) for group in groups),
        multi_project=multi_project,
    )


def _sections_for(
    snapshot: TribePromptsSnapshot,
    *,
    loaded: bool = True,
) -> TribeSectionSnapshot:
    tribe = make_tribe_snapshot()
    return TribeSectionSnapshot(
        panel_identity=tribe.container_identity,
        source_signature=(),
        disk=_TribeDiskSnapshot(
            loaded_sections=frozenset(
                {"prompts", "replies", "slow-tool-calls"} if loaded else ()
            ),
            replies=(),
            slow_tool_calls=(),
            prompts=snapshot,
        ),
        runtime_statistics_loaded=True,
        clan_summaries=(empty_tribe_clan_summaries_snapshot() if loaded else None),
    )


def _render(
    snapshot: TribePromptsSnapshot,
    *,
    level: FoldLevel = FoldLevel.COLLAPSED,
    overrides: dict[str, FoldLevel] | None = None,
) -> Text:
    tribe = make_tribe_snapshot()
    published: list[Any] = []
    detail = build_tribe_detail_text(
        tribe,
        section_snapshot=_sections_for(snapshot),
        fold_level=level,
        section_fold_overrides=overrides or {},
        member_jump_map_publisher=published.append,
    )
    assert isinstance(detail, Text)
    return detail


def _two_unit_snapshot() -> TribePromptsSnapshot:
    tribe = make_tribe_snapshot()
    first, second = tribe.units[0].identity, tribe.units[1].identity
    return _prompts_snapshot(
        (
            TribePromptGroup(
                digest=_digest("First headline.", key="key1"),
                members=(_member(first, "build"),),
            ),
            TribePromptGroup(
                digest=_digest("Second headline.", key="key2"),
                members=(_member(second, "failed"),),
            ),
        )
    )


def test_prompts_absent_while_not_loaded_shows_scanning_tail() -> None:
    tribe = make_tribe_snapshot()
    rendered = build_tribe_detail_text(
        tribe,
        section_snapshot=_sections_for(_prompts_snapshot(()), loaded=False),
        fold_level=FoldLevel.COLLAPSED,
    ).plain

    assert "PROMPTS" not in rendered
    assert rendered.count("⋯ scanning member data…") == 1


def test_prompts_absent_when_loaded_and_empty() -> None:
    for level in FoldLevel:
        rendered = _render(_prompts_snapshot(())).plain
        assert "PROMPTS" not in rendered
        assert "⋯ scanning member data…" not in rendered


def test_level1_shows_headlines_without_unit_labels_or_tags() -> None:
    rendered = _render(_two_unit_snapshot()).plain

    assert "▸ PROMPTS · 2" in rendered
    assert " 0  First headline." in rendered
    assert " 1  Second headline." in rendered
    assert "build · session" not in rendered.split("PROMPTS")[1]
    assert "lines" not in rendered.split("PROMPTS")[1]


def test_distinct_summary_shows_only_when_prompts_are_shared() -> None:
    tribe = make_tribe_snapshot()
    first = tribe.units[0].identity
    shared = _prompts_snapshot(
        (
            TribePromptGroup(
                digest=_digest("Shared headline.", key="shared"),
                members=(_member(first, "build"), _member(first, "build")),
            ),
        )
    )
    rendered = _render(shared).plain

    assert "▸ PROMPTS · 2 · 1 distinct" in rendered
    assert "×2" in rendered


def test_entry_counts_follow_the_section_ladder() -> None:
    tribe = make_tribe_snapshot()
    first = tribe.units[0].identity
    groups = tuple(
        TribePromptGroup(
            digest=_digest(f"Headline {index:03d}.", key=f"key{index:03d}"),
            members=(_member(first, "build"),),
        )
        for index in range(30)
    )
    snapshot = _prompts_snapshot(groups)

    glance = _render(snapshot, level=FoldLevel.COLLAPSED).plain
    assert glance.count("Headline ") == 8
    assert "  +22 more" in glance

    triage = _render(snapshot, level=FoldLevel.EXPANDED).plain
    assert triage.count("Headline ") == 24
    assert "  +6 more" in triage

    inspect = _render(snapshot, level=FoldLevel.FULLY_EXPANDED).plain
    assert "  +6 more" in inspect

    forensics = _render(snapshot, level=FoldLevel.EXHAUSTIVE).plain
    assert forensics.count("Body line.") == 30
    assert "more" not in forensics.split("PROMPTS")[1]


def test_level2_adds_unit_labels_and_tags() -> None:
    tribe = make_tribe_snapshot()
    first = tribe.units[0].identity
    body = "\n".join(f"Body line {index}" for index in range(5)) + "\n"
    snapshot = _prompts_snapshot(
        (
            TribePromptGroup(
                digest=_digest(
                    "Tagged headline.",
                    key="tagged",
                    body=body,
                    chips=("#bd",),
                ),
                members=(_member(first, "build"),),
            ),
        )
    )
    rendered = _render(snapshot, level=FoldLevel.EXPANDED).plain

    assert " 0  build  Tagged headline. · #bd · 5 lines" in rendered


def _warm_tribe_catalog(monkeypatch: Any, *keys: str) -> None:
    """Point tribe digests at fake catalog targets for *keys*."""
    import sase.project_tags.catalog as tag_catalog_module
    from sase.project_tags.catalog import ProjectTagCatalog, ProjectTagTarget

    catalog = ProjectTagCatalog(
        targets=tuple(
            ProjectTagTarget(
                key=key,
                name=key,
                tag=f"+{key}",
                workflow_type="gh",
                vcs_ref=f"#gh:{key}",
                accent="#123456",
            )
            for key in keys
        ),
        accent_palette=("#123456",),
        signature=("tribe-test",),
    )
    monkeypatch.setattr(
        tag_catalog_module, "_CATALOG_CACHE", (catalog.signature, catalog)
    )


def test_level2_project_tag_renders_only_for_multi_project(monkeypatch: Any) -> None:
    _warm_tribe_catalog(monkeypatch, "alpha", "beta")
    tribe = make_tribe_snapshot()
    first = tribe.units[0].identity
    multi = _prompts_snapshot(
        (
            TribePromptGroup(
                digest=_digest("Alpha work.", key="a", project="alpha"),
                members=(_member(first, "build"),),
            ),
            TribePromptGroup(
                digest=_digest("Beta work.", key="b", project="beta"),
                members=(_member(first, "build"),),
            ),
        ),
        multi_project=True,
    )
    rendered = _render(multi, level=FoldLevel.EXPANDED).plain
    assert "+alpha" in rendered and "+beta" in rendered

    single = _prompts_snapshot(
        (
            TribePromptGroup(
                digest=_digest("Alpha work.", key="a", project="alpha"),
                members=(_member(first, "build"),),
            ),
        )
    )
    assert "+alpha" not in _render(single, level=FoldLevel.EXPANDED).plain


def test_digest_project_ignores_patch_unknown_and_cold(monkeypatch: Any) -> None:
    import sase.project_tags.catalog as tag_catalog_module

    _warm_tribe_catalog(monkeypatch, "sase")
    assert _digest_project("#gh:sase do work") == "sase"
    # Patch refs never tagify (D5).
    assert _digest_project("#gh:sase_fix_parser do work") is None
    # Unknown names never gain a made-up tag.
    assert _digest_project("#gh:no-such-xyz do work") is None
    # owner/repo refs never tagify.
    assert _digest_project("#gh:owner/repo do work") is None

    monkeypatch.setattr(tag_catalog_module, "_CATALOG_CACHE", None)
    assert _digest_project("#gh:sase do work") is None


def test_level3_previews_bodies_with_gutter_and_truncation_tail() -> None:
    tribe = make_tribe_snapshot()
    first = tribe.units[0].identity
    body = "\n".join(f"Prompt line {index}" for index in range(14)) + "\n"
    snapshot = _prompts_snapshot(
        (
            TribePromptGroup(
                digest=_digest("Preview headline.", key="preview", body=body),
                members=(_member(first, "build"),),
            ),
        )
    )
    rendered = _render(snapshot, level=FoldLevel.FULLY_EXPANDED).plain

    assert " 0  build · 14 lines" in rendered
    assert "Preview headline." not in rendered.split("│")[0]
    assert "   │ Prompt line 0" in rendered
    assert "   │ Prompt line 9" in rendered
    assert "Prompt line 10" not in rendered
    assert "    │ … +4 more lines" in rendered


def test_level3_multi_member_groups_show_shared_by() -> None:
    tribe = make_tribe_snapshot()
    first, second = tribe.units[0].identity, tribe.units[1].identity
    snapshot = _prompts_snapshot(
        (
            TribePromptGroup(
                digest=_digest("Shared body.", key="shared", body="Line one.\n"),
                members=(
                    _member(first, "build"),
                    _member(second, "failed"),
                ),
            ),
        )
    )
    rendered = _render(snapshot, level=FoldLevel.FULLY_EXPANDED).plain

    assert " 0  1  ×2" in rendered
    assert "    ↳ shared by build, failed" in rendered


def test_level4_renders_full_body_launch_and_safety_cap() -> None:
    tribe = make_tribe_snapshot()
    first = tribe.units[0].identity
    body = "\n".join(f"Full line {index}" for index in range(600)) + "\n"
    snapshot = _prompts_snapshot(
        (
            TribePromptGroup(
                digest=_digest(
                    "Full headline.",
                    key="full",
                    body=body,
                    launch="%id(1) #gh:sase",
                ),
                members=(_member(first, "build"),),
            ),
        )
    )
    rendered = _render(snapshot, level=FoldLevel.EXHAUSTIVE).plain

    assert "    launch  %id(1) #gh:sase" in rendered
    assert "   │ Full line 499" in rendered
    assert "Full line 500" not in rendered
    assert "    │ … +100 more lines" in rendered
    assert "open the agent (press its number) for the rest" in rendered


def test_level4_directives_only_prompt_shows_launch_without_body() -> None:
    tribe = make_tribe_snapshot()
    first = tribe.units[0].identity
    snapshot = _prompts_snapshot(
        (
            TribePromptGroup(
                digest=_digest(
                    "%auto",
                    key="directives",
                    body="",
                    launch="%auto",
                ),
                members=(_member(first, "build"),),
            ),
        )
    )
    rendered = _render(snapshot, level=FoldLevel.EXHAUSTIVE).plain

    assert "    launch  %auto" in rendered
    assert "│" not in rendered.split("launch")[1]


def test_chips_cap_at_three_with_overflow_and_bullet_fallback() -> None:
    text = Text()
    units = [make_tribe_agent(f"unit-{i}", "RUNNING", suffix=f"u{i}") for i in range(4)]
    members = tuple(_member(unit.identity, f"unit-{i}") for i, unit in enumerate(units))
    group = TribePromptGroup(digest=_digest("Many units.", key="many"), members=members)
    snapshot = _prompts_snapshot((group,))
    unit_numbers = {
        units[0].identity: "0",
        units[1].identity: "1",
        # units[2] has no roster number: roster capacity exceeded.
        units[3].identity: "3",
    }
    append_prompts(
        text,
        _sections_for(snapshot),
        level=FoldLevel.COLLAPSED,
        overrides={},
        unit_numbers=unit_numbers,
    )

    assert " 0  1 •+1 ×4  Many units." in text.plain


def test_nested_member_rows_show_relative_labels() -> None:
    tribe = make_tribe_snapshot()
    first = tribe.units[0].identity
    other = make_tribe_agent("other", "RUNNING", suffix="other")
    snapshot = _prompts_snapshot(
        (
            TribePromptGroup(
                digest=_digest("Nested headline.", key="nested"),
                members=(
                    _member(
                        first,
                        "build",
                        member_identity=other.identity,
                        member_label="--code",
                    ),
                ),
            ),
        )
    )
    rendered = _render(snapshot).plain

    assert " 0  › --code  Nested headline." in rendered


def test_per_entry_override_opens_one_prompt() -> None:
    tribe = make_tribe_snapshot()
    first = tribe.units[0].identity
    snapshot = _prompts_snapshot(
        (
            TribePromptGroup(
                digest=_digest("First entry.", key="aaa", body="First body line.\n"),
                members=(_member(first, "build"),),
            ),
            TribePromptGroup(
                digest=_digest("Second entry.", key="bbb", body="Second body line.\n"),
                members=(_member(first, "build"),),
            ),
        )
    )
    rendered = _render(
        snapshot, overrides={"tribe:prompt:bbb": FoldLevel.FULLY_EXPANDED}
    ).plain

    assert " 0  First entry." in rendered
    assert "First body line." not in rendered
    assert "   │ Second body line." in rendered


def test_entry_anchors_are_fold_only_while_heading_is_a_stop() -> None:
    rendered = _render(_two_unit_snapshot())

    markers = [
        span.style.meta[SECTION_MARKER_META_KEY]
        for span in rendered.spans
        if getattr(span.style, "meta", None)
        and SECTION_MARKER_META_KEY in span.style.meta
    ]
    assert "tribe:prompts" in markers
    assert "tribe:prompt:key1" in markers
    fold_only = [
        span.style.meta[SECTION_MARKER_META_KEY]
        for span in rendered.spans
        if getattr(span.style, "meta", None)
        and span.style.meta.get(SECTION_FOLD_ONLY_META_KEY)
    ]
    assert "tribe:prompt:key1" in fold_only
    assert "tribe:prompt:key2" in fold_only
    assert "tribe:prompts" not in fold_only


def test_prompts_sit_after_members_and_before_errors() -> None:
    rendered = _render(_two_unit_snapshot()).plain

    assert rendered.index("TRIBE MEMBERS") < rendered.index("PROMPTS")
    assert rendered.index("PROMPTS") < rendered.index("ERRORS")


def test_level1_render_with_many_groups_never_tokenizes(monkeypatch: Any) -> None:
    tribe = make_tribe_snapshot()
    first = tribe.units[0].identity
    groups = tuple(
        TribePromptGroup(
            digest=_digest(f"Headline {index:03d}.", key=f"perf{index:03d}"),
            members=(_member(first, "build"),),
        )
        for index in range(200)
    )
    snapshot = _prompts_snapshot(groups)
    sections = _sections_for(snapshot)

    def forbidden(_text: str, **_kwargs: object) -> list[Any]:
        raise AssertionError("render paths must replay spans, never tokenize")

    monkeypatch.setattr(
        "sase.xprompt.xprompt_inspect.tokenize",
        forbidden,
    )
    rendered = build_tribe_detail_text(
        tribe,
        section_snapshot=sections,
        fold_level=FoldLevel.COLLAPSED,
    ).plain

    assert sum(1 for line in rendered.splitlines() if "Headline " in line) == 8
    assert "  +192 more" in rendered


def test_empty_tribe_renders_prompts_without_jumps() -> None:
    snapshot = build_agent_tribe_summary_snapshot(
        "empty",
        [],
        panel_collapsed=True,
        now=NOW,
    )
    sections = TribeSectionSnapshot(
        panel_identity=snapshot.container_identity,
        source_signature=(),
        disk=_TribeDiskSnapshot(
            loaded_sections=frozenset({"prompts", "replies", "slow-tool-calls"}),
            replies=(),
            slow_tool_calls=(),
        ),
        runtime_statistics_loaded=True,
        clan_summaries=empty_tribe_clan_summaries_snapshot(),
    )
    rendered = build_tribe_detail_text(
        snapshot,
        section_snapshot=sections,
        fold_level=FoldLevel.COLLAPSED,
    ).plain

    assert "PROMPTS" not in rendered
