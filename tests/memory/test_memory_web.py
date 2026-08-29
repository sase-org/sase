"""Tests for memory-web parsing, lookup, roster, scope, and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.markdown_width import markdown_print_width
from sase.memory.notes import discover_memory_notes
from sase.memory.web import (
    END_MARKER,
    START_MARKER,
    cross_scope_keyword_warnings,
    discover_memory_webs,
    merge_memory_web_scopes,
    render_web_body_with_roster,
    render_web_descriptor_with_roster,
    resolve_memory_strand,
    strip_managed_roster_markers,
    validate_memory_webs,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _descriptor(
    *,
    note_type: str | None = "core",
    parent: str | None = "AGENTS.md",
    roster: str = "inline",
    extra: str = "",
    body: str = "Descriptor body.\n",
) -> str:
    type_line = "" if note_type is None else f"type: {note_type}\n"
    parent_line = "" if parent is None else f"parent: {parent}\n"
    return (
        "---\n"
        f"{type_line}"
        f"{parent_line}"
        "web: true\n"
        f"roster: {roster}\n"
        "roster_label: TERMS\n"
        f"{extra}"
        "---\n\n"
        f"{body}"
    )


def _strand(
    *,
    keyword: str | None = "Alpha Term",
    aliases: str = "aliases: [alpha]\n",
    summary: str = "summary: First term.\n",
    body: str = "Strand body.\n",
) -> str:
    keyword_line = "" if keyword is None else f"keyword: {keyword}\n"
    return f"---\n{keyword_line}{aliases}{summary}---\n\n{body}"


def test_parse_defaults_and_discovery_keeps_note_inventory_flat(tmp_path: Path) -> None:
    _write(tmp_path / "sase" / "memory" / "terms.md", _descriptor(extra=""))
    _write(
        tmp_path / "sase" / "memory" / "terms" / "agent-hood.md",
        _strand(keyword=None, aliases="", summary=""),
    )

    discovery = discover_memory_webs(tmp_path)

    (web,) = discovery.webs
    (strand,) = web.strands
    assert web.roster == "inline"
    assert web.closure == "none"
    assert web.strand_noun == "strand"
    assert strand.keyword == "Agent Hood"
    assert strand.aliases == ()
    assert tuple(note.relative_path for note in discover_memory_notes(tmp_path)) == (
        "sase/memory/terms.md",
    )


def test_parse_accepts_typeless_web_descriptor(tmp_path: Path) -> None:
    _write(
        tmp_path / "sase" / "memory" / "terms.md",
        _descriptor(note_type=None, parent=None, extra="priority: 5\n"),
    )
    _write(tmp_path / "sase" / "memory" / "terms" / "alpha.md", _strand())

    (web,) = discover_memory_webs(tmp_path).webs

    assert web.priority == 5
    assert web.frontmatter["web"] is True
    assert "type" not in web.frontmatter
    assert "parent" not in web.frontmatter


def test_roster_renders_inline_and_replaces_single_region(tmp_path: Path) -> None:
    body = f"Intro.\n\n{START_MARKER}\nold\n{END_MARKER}\n"
    _write(tmp_path / "sase" / "memory" / "terms.md", _descriptor(body=body))
    _write(tmp_path / "sase" / "memory" / "terms" / "alpha.md", _strand())

    (web,) = discover_memory_webs(tmp_path).webs
    content, error = render_web_descriptor_with_roster(web)

    assert error is None
    assert content is not None
    assert "**TERMS:** Alpha Term (alpha)" in content
    assert "old" not in content


def test_descriptor_roster_render_strips_retired_type_and_parent_frontmatter(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "sase" / "memory" / "terms.md",
        _descriptor(extra="description: Terms web.\nmetadata: {owner: docs}\n"),
    )
    _write(tmp_path / "sase" / "memory" / "terms" / "alpha.md", _strand())

    (web,) = discover_memory_webs(tmp_path).webs
    content, error = render_web_descriptor_with_roster(web)

    assert error is None
    assert content is not None
    frontmatter = content.split("---", 2)[1]
    assert "type:" not in frontmatter
    assert "parent:" not in frontmatter
    assert "web: true" in frontmatter
    assert "roster: inline" in frontmatter
    assert "description: Terms web." in frontmatter
    assert "metadata: {owner: docs}" in frontmatter
    assert "Descriptor body." in content


def test_strip_managed_roster_markers_keeps_roster_payload_shape(
    tmp_path: Path,
) -> None:
    body = f"Intro.\n\n{START_MARKER}\nold\n{END_MARKER}\n\n## Next Heading\n"
    _write(tmp_path / "sase" / "memory" / "terms.md", _descriptor(body=body))
    _write(tmp_path / "sase" / "memory" / "terms" / "alpha.md", _strand())

    (web,) = discover_memory_webs(tmp_path).webs
    content, error = render_web_body_with_roster(web)

    assert error is None
    assert content is not None
    assert strip_managed_roster_markers(content) == (
        "Intro.\n\n**TERMS:** Alpha Term (alpha)\n\n## Next Heading\n"
    )


def test_strip_managed_roster_markers_handles_marker_at_start() -> None:
    body = f"{START_MARKER}\n\nPayload.\n\n{END_MARKER}\n"

    assert strip_managed_roster_markers(body) == "\nPayload.\n"


def test_strip_managed_roster_markers_returns_unmarked_body_unchanged() -> None:
    body = "Intro.\n\nPayload.\n"

    assert strip_managed_roster_markers(body) == body


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (f"{START_MARKER}\nPayload.\n{END_MARKER}\n", "Payload.\n"),
        (f"{START_MARKER}\nPayload.\n{END_MARKER}", "Payload."),
    ],
)
def test_strip_managed_roster_markers_preserves_trailing_newline_shape(
    body: str, expected: str
) -> None:
    assert strip_managed_roster_markers(body) == expected


def test_roster_inline_uses_rust_display_aliases(tmp_path: Path) -> None:
    _write(tmp_path / "sase" / "memory" / "terms.md", _descriptor())
    _write(
        tmp_path / "sase" / "memory" / "terms" / "proc.md",
        _strand(
            keyword="Proc",
            aliases="aliases: [procs, background task, background tasks]\n",
            summary="summary: A background task.\n",
            body="Procs live under ~/.sase/procs.\n",
        ),
    )
    _write(
        tmp_path / "sase" / "memory" / "terms" / "agent-hood.md",
        _strand(
            keyword="Agent Hood",
            aliases="aliases: [hood, agent neighborhood]\n",
            summary="summary: A group of agents.\n",
            body="An agent hood is a group of agents named alike.\n",
        ),
    )

    (web,) = discover_memory_webs(tmp_path).webs
    content, error = render_web_descriptor_with_roster(web)

    assert error is None
    assert content is not None
    assert (
        "**TERMS:** Agent Hood (hood, agent neighborhood); Proc (background task)"
        in content
    )


def test_roster_inline_escapes_markdown_punctuation(tmp_path: Path) -> None:
    _write(tmp_path / "sase" / "memory" / "terms.md", _descriptor())
    _write(
        tmp_path / "sase" / "memory" / "terms" / "star.md",
        _strand(
            keyword="Star*Term",
            aliases="aliases: [under_score]\n",
            summary="summary: Has punctuation.\n",
            body="Body for a punctuated term.\n",
        ),
    )

    (web,) = discover_memory_webs(tmp_path).webs
    content, error = render_web_descriptor_with_roster(web)

    assert error is None
    assert content is not None
    assert r"Star\*Term (under\_score)" in content


def test_roster_inline_wraps_at_the_configured_prose_width(tmp_path: Path) -> None:
    _write(tmp_path / "sase" / "memory" / "terms.md", _descriptor())
    for index in range(20):
        _write(
            tmp_path / "sase" / "memory" / "terms" / f"term-{index}.md",
            _strand(
                keyword=f"Term Number {index}",
                aliases=f"aliases: [alias-{index}-one, alias-{index}-two]\n",
                summary=f"summary: Definition for term {index}.\n",
                body=f"Body for term {index}.\n",
            ),
        )

    (web,) = discover_memory_webs(tmp_path).webs
    content, error = render_web_descriptor_with_roster(web)

    assert error is None
    assert content is not None
    width = markdown_print_width()
    assert all(len(line) <= width for line in content.splitlines())
    assert "\n" in content.split(START_MARKER, 1)[1].split(END_MARKER, 1)[0].strip()


def test_roster_wraps_long_list_bullets_to_the_configured_prose_width(
    tmp_path: Path,
) -> None:
    long_summary = (
        "summary: This decision summary is deliberately long enough that the "
        "rendered bullet line must wrap to stay inside the configured prose "
        "width instead of round-tripping as one unwrapped line.\n"
    )
    body = f"Intro.\n\n{START_MARKER}\n{END_MARKER}\n"
    _write(
        tmp_path / "sase" / "memory" / "terms.md", _descriptor(roster="list", body=body)
    )
    _write(
        tmp_path / "sase" / "memory" / "terms" / "alpha.md",
        _strand(aliases="", summary=long_summary),
    )

    (web,) = discover_memory_webs(tmp_path).webs
    content, error = render_web_descriptor_with_roster(web)

    assert error is None
    assert content is not None
    width = markdown_print_width()
    assert all(len(line) <= width for line in content.splitlines())
    assert "- **Alpha Term** (`alpha`) - This decision summary" in content
    assert "\n  round-tripping as one unwrapped line." in content


def test_roster_marker_validation_blocks_unbalanced_or_duplicate_regions(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "sase" / "memory" / "terms.md",
        _descriptor(body=f"{START_MARKER}\nmissing end\n"),
    )
    _write(tmp_path / "sase" / "memory" / "terms" / "alpha.md", _strand())

    report = validate_memory_webs(discover_memory_webs(tmp_path))

    assert any("unbalanced" in blocker for blocker in report.blockers)


@pytest.mark.parametrize(
    ("descriptor", "strand", "expected"),
    [
        (_descriptor(roster="list"), _strand(summary=""), "summary is required"),
        (_descriptor(), "---\ntype: core\n---\n\nBody\n", "must not declare type"),
        (_descriptor(), "---\naliases: bad\n---\n\nBody\n", "aliases must be"),
        (_descriptor(), _strand(keyword="Alpha Term"), "ambiguous normalized"),
    ],
)
def test_validation_blocks_strand_fail_closed_classes(
    tmp_path: Path,
    descriptor: str,
    strand: str,
    expected: str,
) -> None:
    _write(tmp_path / "sase" / "memory" / "terms.md", descriptor)
    _write(tmp_path / "sase" / "memory" / "terms" / "alpha.md", _strand())
    _write(tmp_path / "sase" / "memory" / "terms" / "beta.md", strand)

    report = validate_memory_webs(discover_memory_webs(tmp_path))

    assert any(expected in blocker for blocker in report.blockers)


def test_validation_blocks_orphan_mismatch_reserved_nested_and_symlink(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "sase" / "memory" / "patch.md", _descriptor())
    _write(tmp_path / "sase" / "memory" / "patch" / "alpha.md", _strand())
    _write(tmp_path / "sase" / "memory" / "orphan" / "alpha.md", _strand())
    _write(
        tmp_path / "sase" / "memory" / "plain.md",
        "---\ntype: reference\nparent: AGENTS.md\n---\nPlain\n",
    )
    _write(tmp_path / "sase" / "memory" / "plain" / "alpha.md", _strand())
    _write(tmp_path / "sase" / "memory" / "patch" / "nested" / "x.md", "x")
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "sase" / "memory" / "patch" / "escape.md").symlink_to(
        outside / "escape.md"
    )

    report = validate_memory_webs(discover_memory_webs(tmp_path))

    joined = "\n".join(report.blockers)
    assert "reserved" in joined
    assert "has no descriptor note" in joined
    assert "does not declare web: true" in joined
    assert "nested directories" in joined
    assert "symlink resolves outside" in joined


@pytest.mark.parametrize(
    ("descriptor", "expected"),
    [
        (
            _descriptor(extra="priority: true\n"),
            "priority must be a non-negative integer",
        ),
    ],
)
def test_validation_blocks_bad_memory_web_priority(
    tmp_path: Path,
    descriptor: str,
    expected: str,
) -> None:
    _write(tmp_path / "sase" / "memory" / "terms.md", descriptor)
    _write(tmp_path / "sase" / "memory" / "terms" / "alpha.md", _strand())

    report = validate_memory_webs(discover_memory_webs(tmp_path))

    assert any(expected in blocker for blocker in report.blockers)


def test_validation_allows_legacy_reference_web_priority(tmp_path: Path) -> None:
    _write(
        tmp_path / "sase" / "memory" / "terms.md",
        _descriptor(note_type="reference", extra="priority: 5\n"),
    )
    _write(tmp_path / "sase" / "memory" / "terms" / "alpha.md", _strand())

    discovery = discover_memory_webs(tmp_path)
    report = validate_memory_webs(discovery)

    assert report.blockers == ()
    assert discovery.webs[0].priority == 5


def test_lookup_precedence_and_scope_origin_tracking(tmp_path: Path) -> None:
    _write(tmp_path / "project" / "sase" / "memory" / "terms.md", _descriptor())
    _write(
        tmp_path / "project" / "sase" / "memory" / "terms" / "alpha.md",
        _strand(keyword="Project Alpha", aliases="aliases: [shared]\n"),
    )
    _write(tmp_path / "home" / "sase" / "memory" / "terms.md", _descriptor())
    _write(
        tmp_path / "home" / "sase" / "memory" / "terms" / "alpha.md",
        _strand(keyword="Home Alpha", aliases="aliases: [shared]\n"),
    )
    _write(
        tmp_path / "home" / "sase" / "memory" / "terms" / "beta.md",
        _strand(keyword="Home Beta", aliases="aliases: [home beta]\n"),
    )
    project_web = discover_memory_webs(tmp_path / "project").webs[0]
    home_web = discover_memory_webs(tmp_path / "home").webs[0]

    (merged,) = merge_memory_web_scopes(
        project_webs=(project_web,),
        home_webs=(home_web,),
    )

    assert merged.origins["alpha"].scope == "project"
    assert merged.origins["beta"].scope == "home"
    assert resolve_memory_strand(project_web, "shared").slug == "alpha"
    assert cross_scope_keyword_warnings(
        project_webs=(project_web,),
        home_webs=(home_web,),
    )
