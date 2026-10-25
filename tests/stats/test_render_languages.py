"""Renderer contracts for language identity and the card block."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from sase.stats.project.languages import language_breakdown
from sase.stats.render.languages import (
    language_label,
    language_share_label,
    render_language_card_block,
)
from sase.stats.render.languages import (
    _language_card_cap as language_card_cap,
)
from sase.stats.render.languages import _language_color as language_color
from tests.stats._project_render_fixtures import one_project_view, render_context


def _export_text(renderable, ctx) -> str:
    console = Console(
        width=ctx.width,
        height=256,
        color_system="truecolor" if ctx.color else None,
        no_color=not ctx.color,
        force_terminal=True,
        highlight=False,
        record=True,
        legacy_windows=False,
        file=StringIO(),
        emoji=ctx.unicode,
    )
    console.print(renderable)
    return console.export_text(styles=False)


def test_every_core_id_has_label() -> None:
    ids = [
        "python",
        "rust",
        "typescript",
        "tsx",
        "javascript",
        "jsx",
        "css",
        "html",
        "lua",
        "sh",
        "bash",
        "zsh",
        "fish",
        "json",
        "yaml",
        "toml",
        "xml",
        "sql",
        "markdown",
        "rst",
        "jinja",
        "diff",
        "c",
        "cpp",
        "go",
        "java",
        "ruby",
        "perl",
        "php",
        "awk",
        "r",
        "powershell",
        "docker",
        "make",
        "swift",
        "kotlin",
        "objective-c",
        "objective-c++",
        "dart",
        "scala",
        "groovy",
        "csharp",
        "elixir",
        "erlang",
        "haskell",
        "ocaml",
        "clojure",
        "elm",
        "zig",
        "nim",
        "julia",
        "batch",
        "scss",
        "sass",
        "less",
        "vue",
        "graphql",
        "terraform",
        "nix",
        "protobuf",
        "cmake",
        "vim",
    ]
    for language_id in ids:
        assert language_label(language_id) != language_id or language_id in {"r", "c"}
    assert language_label("python") == "Python"
    assert language_label("rust") == "Rust"
    assert language_label("sh") == "Shell"
    assert language_label("cpp") == "C++"
    assert language_label("swift") == "Swift"
    assert language_label("csharp") == "C#"
    assert language_label("vim") == "Vim script"


def test_new_language_colors_use_shared_slots() -> None:
    assert language_color("swift") == "#8a8984"
    assert language_color("kotlin") == "#8a8984"
    assert language_color("scss") == "#9085e9"
    assert language_color("sass") == "#9085e9"
    assert language_color("less") == "#9085e9"


def test_unknown_id_neutral_plus_capitalized() -> None:
    assert language_color("cobol") == "#8a8984"
    assert language_label("cobol") == "Cobol"


def test_share_labels() -> None:
    assert language_share_label(0, 100) == "0%"
    assert language_share_label(1, 10_000) == "<1%"
    assert language_share_label(999, 1_000) == ">99%"
    assert language_share_label(50, 100) == "50%"
    assert language_share_label(100, 100) == "100%"


def test_card_cap_and_folded() -> None:
    assert language_card_cap(render_context(width=120)) == 4
    assert language_card_cap(render_context(width=50)) == 3
    view = one_project_view()
    breakdown = language_breakdown(view)
    assert breakdown is not None
    block = render_language_card_block(breakdown, render_context(width=120))
    assert block is not None
    text = _export_text(block, render_context(width=120))
    assert "+5 more" in text
    assert "JSON, Lua, Bash, Shell, Jinja" in text


def test_unknown_pinned_outside_cap() -> None:
    view = one_project_view()
    breakdown = language_breakdown(view)
    assert breakdown is not None
    block = render_language_card_block(breakdown, render_context(width=50))
    assert block is not None
    text = _export_text(block, render_context(width=50))
    assert "? " in text
    assert "1.2k" in text


def test_no_repo_note_single_repo_project() -> None:
    from sase.stats.project.languages import (
        LanguageBreakdown,
        LanguageRow,
        LanguageSlice,
    )

    breakdown = LanguageBreakdown(
        total_lines=100,
        total_files=10,
        rows=(
            LanguageRow(
                language="python",
                lines=100,
                files=10,
                share=1.0,
                slices=(
                    LanguageSlice(
                        project_key="k",
                        project_label="sase",
                        repo_id="primary:sase",
                        repo_name="sase",
                        lines=100,
                        files=10,
                    ),
                ),
            ),
        ),
        zero_languages=(),
        unmeasured=(),
        overlap_lines=0,
        many_projects=False,
        measured_repos=1,
        configured_repos=1,
    )
    block = render_language_card_block(breakdown, render_context(width=120))
    assert block is not None
    text = _export_text(block, render_context(width=120))
    assert "Python" in text
    # No repo note when the project has a single code repo.
    assert "sase" not in text.replace("Python", "")


def test_card_bar_share_align_with_by_repo() -> None:
    from sase.stats.render import render_project_stats

    ctx = render_context(width=120)
    text = _export_text(render_project_stats(one_project_view(), "model", ctx), ctx)
    by_repo_offsets: list[int] = []
    by_lang_offsets: list[int] = []
    in_by_repo = False
    in_by_lang = False
    for line in text.splitlines():
        if "by repo" in line:
            in_by_repo = True
            in_by_lang = False
        elif "by lang" in line:
            in_by_repo = False
            in_by_lang = True
        elif line.strip().startswith(("OUTPUT", "CODE", "RUNS")):
            in_by_repo = False
            in_by_lang = False
        if in_by_repo and "%" in line and ("█" in line or "▏" in line):
            glyph = "█" if "█" in line else "▏"
            by_repo_offsets.append(line.index(glyph))
        if in_by_lang and "%" in line and ("█" in line or "▏" in line):
            glyph = "█" if "█" in line else "▏"
            by_lang_offsets.append(line.index(glyph))
    assert by_repo_offsets and by_lang_offsets
    assert max(by_repo_offsets) - min(by_repo_offsets) <= 2
    assert max(by_lang_offsets) - min(by_lang_offsets) <= 2
    assert abs(by_repo_offsets[0] - by_lang_offsets[0]) <= 4
