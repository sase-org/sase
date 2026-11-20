"""Compile-time compact list-roster styles (bundle_trim)."""

from __future__ import annotations

from pathlib import Path

from sase.memory.web import discover_memory_webs, render_strand_roster
from sase.memory.web.models import MemoryWeb
from sase.memory.web.roster import (
    render_web_body_with_roster,
    render_web_descriptor_with_roster,
)

_SUPERSEDED_NOTE = (
    "_Summaries of superseded entries omitted to fit the provider budget; "
    "read one with `sase memory read decisions:<keyword>`._"
)
_ALL_NOTE = (
    "_Entry summaries omitted to fit the provider budget; "
    "read one with `sase memory read decisions:<keyword>`._"
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _strand(keyword: str, summary: str, metadata: str = "") -> str:
    return f"---\nkeyword: {keyword}\nsummary: {summary}\n{metadata}---\n\nBody.\n"


def _seed(root: Path, *, roster: str = "list", superseded: bool = True) -> MemoryWeb:
    memory = root / "sase" / "memory"
    _write(
        memory / "decisions.md",
        f"---\nweb: true\nroster: {roster}\nroster_label: RECORDS\n---\n\n"
        "# Decisions\n\nDescriptor body.\n",
    )
    old_meta = (
        "metadata:\n  status: superseded\n  superseded_by: beta\n" if superseded else ""
    )
    partial_meta = (
        "metadata:\n  status: superseded-in-part\n  superseded_by: beta\n"
        if superseded
        else ""
    )
    _write(memory / "decisions" / "alpha.md", _strand("Alpha", "Old rule.", old_meta))
    _write(memory / "decisions" / "beta.md", _strand("Beta", "Current rule."))
    _write(
        memory / "decisions" / "gamma.md",
        _strand("Gamma", "Partly replaced rule.", partial_meta),
    )
    (web,) = discover_memory_webs(root).webs
    return web


def test_default_style_is_unchanged(tmp_path: Path) -> None:
    web = _seed(tmp_path)
    assert render_strand_roster(web, compaction=None) == render_strand_roster(web)
    assert "Old rule." in render_strand_roster(web)


def test_superseded_style_drops_only_superseded_summaries(tmp_path: Path) -> None:
    web = _seed(tmp_path)
    roster = render_strand_roster(web, compaction="superseded")
    lines = roster.splitlines()

    assert lines[0] == "1. **Alpha** (`alpha`) _[superseded by `beta`]_"
    assert "Old rule." not in roster
    assert "Partly replaced rule." not in roster
    assert "3. **Gamma** (`gamma`) _[partly superseded by `beta`]_" in lines
    assert "2. **Beta** (`beta`)" in lines
    assert "   - Current rule." in lines
    assert lines[-2:] == ["", _SUPERSEDED_NOTE]
    assert "`sase memory read decisions:<keyword>`" in lines[-1]


def test_all_style_keeps_number_title_and_slug_only(tmp_path: Path) -> None:
    web = _seed(tmp_path)
    roster = render_strand_roster(web, compaction="all")

    assert roster.splitlines() == [
        "1. **Alpha** (`alpha`)",
        "2. **Beta** (`beta`)",
        "3. **Gamma** (`gamma`)",
        "",
        _ALL_NOTE,
    ]


def test_superseded_style_without_superseded_strands_is_identical(
    tmp_path: Path,
) -> None:
    web = _seed(tmp_path, superseded=False)
    assert render_strand_roster(web, compaction="superseded") == render_strand_roster(
        web
    )


def test_inline_roster_ignores_compaction(tmp_path: Path) -> None:
    web = _seed(tmp_path, roster="inline")
    assert render_strand_roster(web, compaction="all") == render_strand_roster(web)


def test_compaction_is_a_projection_only(tmp_path: Path) -> None:
    """The compacted body never reaches the descriptor writer."""
    web = _seed(tmp_path)
    content, error = render_web_descriptor_with_roster(web)
    assert error is None and content is not None
    assert "Old rule." in content
    assert "omitted to fit" not in content

    body, error = render_web_body_with_roster(web, compaction="all")
    assert error is None and body is not None
    assert "Old rule." not in body
    assert "Current rule." not in body
    assert body.count("<!-- sase:strands -->") == 1
