"""Rendering coverage for the grouped ``@`` reference menu."""

from __future__ import annotations

import pytest
from rich.text import Text
from textual.widgets import Static

from sase.ace.tui.widgets._prompt_input_bar_completion_panel import (
    _artifact_ref_completion_subtitle,
    _at_reference_group_rule_needed,
    _at_reference_panel_title,
)
from sase.ace.tui.widgets._completion_match_highlight import append_highlighted
from sase.ace.tui.widgets._prompt_input_bar_completion_rows import (
    append_artifact_ref_completion_row,
    append_at_reference_group_rule,
    artifact_ref_kind_label_width,
    at_reference_directory_display,
)
from sase.ace.tui.widgets.artifact_ref_completion import (
    ARTIFACT_REF_COMPLETION_KIND,
    AtReferenceFileCompletionMetadata,
    ArtifactRefKindCompletionMetadata,
    ArtifactRefPayloadCompletionMetadata,
    ArtifactRefPayloadSource,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar

from ._completion_helpers import CompletionTestApp


def _kind(
    name: str,
    *,
    builtin: bool = True,
    detail: str = "builtin",
) -> CompletionCandidate:
    return CompletionCandidate(
        display=name,
        insertion=f"@{name}:",
        is_dir=False,
        name=name,
        metadata=ArtifactRefKindCompletionMetadata(name, builtin, detail),
    )


def _file(name: str, *, is_dir: bool = False) -> CompletionCandidate:
    display = f"{name}/" if is_dir else name
    return CompletionCandidate(
        display=display,
        insertion=f"@{display}",
        is_dir=is_dir,
        name=name,
        metadata=AtReferenceFileCompletionMetadata(is_dir, ""),
    )


def _payload(name: str) -> CompletionCandidate:
    return CompletionCandidate(
        display=name,
        insertion=f"@plans:{name}",
        is_dir=False,
        name=name,
        metadata=ArtifactRefPayloadCompletionMetadata(
            kind="plans",
            payload=name,
            source="document",
        ),
    )


def _entity_payload(
    display: str,
    source: ArtifactRefPayloadSource,
) -> CompletionCandidate:
    return CompletionCandidate(
        display=display,
        insertion=f"@{source}:payload",
        is_dir=False,
        name=display,
        metadata=ArtifactRefPayloadCompletionMetadata(
            kind=source,
            payload="payload",
            source=source,
        ),
    )


def _render_row(
    candidate: CompletionCandidate,
    *,
    selected: bool = False,
    kind_width: int = 0,
) -> Text:
    content = Text()
    append_artifact_ref_completion_row(
        content,
        candidate,
        selected,
        kind_width,
    )
    return content


def test_artifact_rows_use_three_cell_badge_and_aligned_details() -> None:
    rows = [
        _kind("bug"),
        _kind(
            "plans",
            builtin=False,
            detail="document · ~/plans",
        ),
    ]
    width = artifact_ref_kind_label_width(rows)

    rendered = [_render_row(row, kind_width=width).plain for row in rows]

    assert width == len("plans")
    assert rendered == [
        "@  bug    builtin",
        "@  plans  document · ~/plans",
    ]
    assert rendered[0].index("builtin") == rendered[1].index("document")


def test_file_rows_reuse_file_menu_glyph_and_color_anatomy() -> None:
    directory = _render_row(_file("src", is_dir=True), selected=True)
    regular_file = _render_row(_file("Justfile"), selected=True)

    assert directory.plain == "📁 src/"
    assert regular_file.plain == "📄 Justfile"
    assert any(str(span.style) == "bold #87D7FF" for span in directory.spans)
    assert any(str(span.style) == "bold" for span in regular_file.spans)


def test_shared_highlight_helper_splits_directory_basename_and_match_runs() -> None:
    rendered = Text()

    append_highlighted(
        rendered,
        "202607/bundle/site.md",
        ((14, 18),),
        base_style="bold",
        segment_split=14,
    )

    assert rendered.plain == "202607/bundle/site.md"
    assert [
        (rendered.plain[span.start : span.end], str(span.style))
        for span in rendered.spans
    ] == [
        ("202607/bundle/", "dim"),
        ("site", "bold #FFD700"),
        (".md", "bold"),
    ]


def test_payload_row_is_path_first_with_highlighted_path_and_title() -> None:
    path = "202607/sase_sites_hub/sase_sites_hub.md"
    candidate = CompletionCandidate(
        display=path,
        insertion=f"@research:{path}",
        is_dir=False,
        name="sase_sites_hub.md",
        metadata=ArtifactRefPayloadCompletionMetadata(
            kind="research",
            payload=path,
            source="document",
            label="SASE Sites Hub",
            detail="research",
            age="3d",
            label_match=((27, 31),),
            title_match=((5, 9),),
            match_tier=2,
        ),
    )

    rendered = _render_row(candidate)
    gold = [
        rendered.plain[span.start : span.end]
        for span in rendered.spans
        if str(span.style) == "bold #FFD700"
    ]

    assert rendered.plain == (
        "[D] 202607/sase_sites_hub/sase_sites_hub.md"
        "  SASE Sites Hub  ·  research  ·  3d"
    )
    assert gold == ["site", "Site"]
    assert any(
        rendered.plain[span.start : span.end] == "202607/sase_sites_hub/"
        and str(span.style) == "dim"
        for span in rendered.spans
    )


def test_commit_row_dims_repo_segment_and_omits_duplicate_detail() -> None:
    candidate = CompletionCandidate(
        display="sase-core@5143cb981f0a",
        insertion="@commit:sase-core@5143cb981f0a",
        is_dir=False,
        name="sase-core@5143cb981f0a",
        metadata=ArtifactRefPayloadCompletionMetadata(
            kind="commit",
            payload="sase-core@5143cb981f0a",
            source="commit",
            label="fix(stats): expose payload inventory",
            detail="",
            age="3h",
            scope="sase-core",
            rank=0,
        ),
    )

    rendered = _render_row(candidate)

    assert rendered.plain == (
        "[G] sase-core@5143cb981f0a  fix(stats): expose payload inventory  ·  3h"
    )
    assert any(
        rendered.plain[span.start : span.end] == "sase-core@"
        and str(span.style) == "dim"
        for span in rendered.spans
    )
    assert any(
        rendered.plain[span.start : span.end] == "5143cb981f0a"
        and str(span.style) == "bold"
        for span in rendered.spans
    )


def test_payload_tail_truncates_without_eliding_the_reference_path() -> None:
    path = "202607/bundle/important.md"
    candidate = CompletionCandidate(
        display=path,
        insertion=f"@plans:{path}",
        is_dir=False,
        name="important.md",
        metadata=ArtifactRefPayloadCompletionMetadata(
            kind="plans",
            payload=path,
            source="document",
            label="An intentionally long plan title",
            detail="plans",
            age="now",
        ),
    )
    content = Text()

    append_artifact_ref_completion_row(
        content,
        candidate,
        False,
        inner_width=42,
    )

    assert path in content.plain
    assert content.plain.endswith("...")
    assert content.cell_len <= 40


def test_kind_and_file_rows_highlight_wire_runs() -> None:
    kind = _kind("research")
    kind = CompletionCandidate(
        display=kind.display,
        insertion=kind.insertion,
        is_dir=kind.is_dir,
        name=kind.name,
        metadata=ArtifactRefKindCompletionMetadata(
            "research",
            False,
            "document",
            ((0, 1), (2, 3), (5, 8)),
            3,
        ),
    )
    file_row = CompletionCandidate(
        display="_file_completion_base.py",
        insertion="@_file_completion_base.py",
        is_dir=False,
        name="_file_completion_base.py",
        metadata=AtReferenceFileCompletionMetadata(
            False,
            "",
            ((1, 2), (6, 7), (17, 18)),
            3,
        ),
    )

    assert [
        _render_row(kind).plain[span.start : span.end]
        for span in _render_row(kind).spans
        if str(span.style) == "bold #FFD700"
    ] == ["r", "s", "rch"]
    assert [
        _render_row(file_row).plain[span.start : span.end]
        for span in _render_row(file_row).spans
        if str(span.style) == "bold #FFD700"
    ] == ["f", "c", "b"]


def test_artifact_subtitle_reports_fuzzy_matches_and_unscanned_rows() -> None:
    row = CompletionCandidate(
        display="site.md",
        insertion="@research:site.md",
        is_dir=False,
        name="site.md",
        metadata=ArtifactRefPayloadCompletionMetadata(
            "research",
            "site.md",
            "document",
            match_tier=2,
        ),
    )

    subtitle = _artifact_ref_completion_subtitle([row], 3, 305, 1203, 80)
    prefix_subtitle = _artifact_ref_completion_subtitle(
        [_payload("202607/plan.md")],
        1,
        305,
        0,
        80,
    )

    assert subtitle.plain == "~ fuzzy · 3 of 305 · ⚠ 1203 not scanned"
    assert prefix_subtitle.plain == "1 of 305"


def test_artifact_subtitle_advertises_suppressed_files_only_when_present() -> None:
    row = _kind("file")

    suppressed = _artifact_ref_completion_subtitle(
        [row],
        0,
        0,
        0,
        80,
        files_suppressed=True,
    )
    visible = _artifact_ref_completion_subtitle([row], 0, 0, 0, 80)

    assert suppressed.plain == "[^T] files"
    assert any(
        suppressed.plain[span.start : span.end] == "[^T] files"
        and str(span.style) == "dim"
        for span in suppressed.spans
    )
    assert visible.plain == ""


@pytest.mark.parametrize(
    ("source", "badge"),
    (("bead", "[◆] "), ("agent", "[A] ")),
)
def test_entity_badges_use_documented_four_cell_width(
    source: ArtifactRefPayloadSource,
    badge: str,
) -> None:
    rendered = _render_row(_entity_payload("row", source))

    assert Text(badge).cell_len == 4
    assert rendered.plain == f"{badge}row"


def test_group_rule_is_padded_to_inner_width_and_shortens_home(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    directory = str(tmp_path / "workspace")
    content = Text()

    append_at_reference_group_rule(content, directory, 42)

    assert at_reference_directory_display(directory) == "~/workspace"
    assert content.plain.startswith("── files · ~/workspace")
    assert content.cell_len == 42
    assert set(content.plain.removeprefix("── files · ~/workspace")) == {"─"}


def test_group_rule_and_adaptive_titles_follow_actual_groups() -> None:
    artifacts = [_kind("commit")]
    files = [_file("src", is_dir=True)]
    payloads = [_payload("202607/plan.md")]
    directory = "~/project"

    assert _at_reference_group_rule_needed([*artifacts, *files]) is True
    assert _at_reference_group_rule_needed(artifacts) is False
    assert _at_reference_group_rule_needed(files) is False
    assert _at_reference_panel_title("artifact kinds", artifacts, directory) == (
        "@ artifact kinds"
    )
    assert _at_reference_panel_title("artifact kinds", files, directory) == (
        "@ ~/project"
    )
    assert (
        _at_reference_panel_title(
            "artifact kinds",
            [*artifacts, *files],
            directory,
        )
        == "@ reference"
    )
    assert (
        _at_reference_panel_title(
            "plans: documents",
            payloads,
            directory,
        )
        == "plans: documents"
    )


async def test_panel_renders_rule_between_ordered_groups() -> None:
    app = CompletionTestApp()
    rows = [
        _kind("commit"),
        _kind("plans", builtin=False, detail="document · ~/plans"),
        _file("src", is_dir=True),
        _file("Justfile"),
    ]
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        panel = bar.query_one("#prompt-completion", Static)

        bar.show_file_completions(
            "artifact kinds",
            rows,
            selected_index=0,
            completion_kind=ARTIFACT_REF_COMPLETION_KIND,
            group_rule=True,
            group_directory="~/project",
        )
        await pilot.pause()

        rendered = panel.render().plain
        assert rendered.index("@  commit") < rendered.index("── files")
        assert rendered.index("── files") < rendered.index("📁 src/")
        assert rendered.index("📁 src/") < rendered.index("📄 Justfile")
        rule = next(line for line in rendered.splitlines() if "── files" in line)
        assert rule.endswith("─")
        assert rule.count("─") > 2
        assert panel.border_title == "@ reference"
