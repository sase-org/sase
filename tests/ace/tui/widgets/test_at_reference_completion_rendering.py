"""Rendering coverage for the grouped ``@`` reference menu."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from sase.ace.tui.widgets._prompt_input_bar_completion_panel import (
    _at_reference_group_rule_needed,
    _at_reference_panel_title,
)
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
    assert any(str(span.style) == "bold cyan" for span in directory.spans)
    assert any(str(span.style) == "bold" for span in regular_file.spans)


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
