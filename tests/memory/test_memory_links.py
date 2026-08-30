"""Tests for authored memory-link scanning and target resolution."""

from __future__ import annotations

from pathlib import Path

from sase.memory.link_resolve import (
    MemoryNoteLinkTarget,
    MemoryStrandLinkTarget,
    MemoryWebDescriptorLinkTarget,
    UnresolvedMemoryLinkTarget,
    resolve_memory_link_target,
)
from sase.memory.links import scan_memory_links
from sase.memory.notes import discover_memory_notes, parse_memory_note_text
from sase.memory.web import discover_scoped_memory_webs, resolve_memory_strand


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _note(body: str = "# Body\n", *, description: str = "A note.") -> str:
    return f"---\ntype: reference\nparent: AGENTS.md\ndescription: {description}\n---\n{body}"


def _descriptor(
    *,
    link_reference: str | None = None,
    closure: str | None = None,
    description: str = "A web.",
) -> str:
    extra = ""
    if closure is not None:
        extra += f"closure: {closure}\n"
    elif link_reference is not None:
        extra += f"link_reference: {link_reference}\n"
    return (
        "---\n"
        "web: true\n"
        f"description: {description}\n"
        "roster: inline\n"
        f"{extra}"
        "---\n\n"
        "Descriptor body.\n"
    )


def _strand(
    *,
    keyword: str,
    aliases: str = "",
    summary: str = "A strand.",
    body: str = "Strand body.\n",
) -> str:
    aliases_line = f"aliases: [{aliases}]\n" if aliases else ""
    return f"---\nkeyword: {keyword}\n{aliases_line}summary: {summary}\n---\n\n{body}"


def _seed_memory(root: Path) -> None:
    _write(root / "sase" / "memory" / "symvision.md", _note(description="Symvision."))
    _write(
        root / "sase" / "memory" / "glossary.md",
        _descriptor(closure="mentions", description="Glossary terms."),
    )
    _write(
        root / "sase" / "memory" / "glossary" / "stitch.md",
        _strand(
            keyword="Stitch",
            aliases="commit-ish",
            summary="A change record.",
            body="A Stitch mentions Patch inside its body.\n",
        ),
    )
    _write(
        root / "sase" / "memory" / "glossary" / "patch.md",
        _strand(keyword="Patch", summary="A proposed change."),
    )
    _write(
        root / "sase" / "memory" / "decisions.md",
        _descriptor(description="Decision records."),
    )
    _write(
        root / "sase" / "memory" / "decisions" / "single-turn-agents.md",
        _strand(
            keyword="Agents Are Single-Turn",
            aliases="single turn",
            summary="Agents have one provider turn.",
        ),
    )


def _universe(root: Path):
    return (
        discover_memory_notes(root),
        discover_scoped_memory_webs(root, root / "home"),
    )


def test_scan_memory_links_marks_inline_and_reference_spans() -> None:
    body = "See [[glossary:stitch]] and ![[decisions/single-turn-agents]]."

    links = scan_memory_links(body)

    assert links[0].raw == "[[glossary:stitch]]"
    assert links[0].target == "glossary:stitch"
    assert links[0].inline is False
    assert links[0].span == (body.index("[["), body.index("]]") + 2)
    assert links[1].raw == "![[decisions/single-turn-agents]]"
    assert links[1].target == "decisions/single-turn-agents"
    assert links[1].inline is True


def test_scan_memory_links_dedupes_by_target_and_inline_flag() -> None:
    body = "[[alpha]] [[alpha]] ![[alpha]] [[ beta ]] [[beta]]"

    links = scan_memory_links(body)

    assert [(link.target, link.inline, link.raw) for link in links] == [
        ("alpha", False, "[[alpha]]"),
        ("alpha", True, "![[alpha]]"),
        ("beta", False, "[[ beta ]]"),
    ]


def test_scan_memory_links_skips_fenced_and_inline_code() -> None:
    body = (
        "Keep [[live]].\n"
        "Ignore `[[inline]]` and `![[inline-force]]`.\n"
        "```md\n"
        "[[fenced]]\n"
        "![[fenced-inline]]\n"
        "```\n"
    )

    links = scan_memory_links(body)

    assert [link.target for link in links] == ["live"]


def test_scan_memory_links_ignores_real_xprompts_inline_code_case() -> None:
    text = Path("sase/memory/xprompts.md").read_text(encoding="utf-8")
    body = parse_memory_note_text(text, "xprompts.md").body

    links = scan_memory_links(body)

    assert all(link.raw != "[[ ... ]]" for link in links)


def test_resolve_colon_target_uses_existing_strand_lookup(tmp_path: Path) -> None:
    _seed_memory(tmp_path)
    notes, scoped_webs = _universe(tmp_path)

    target = resolve_memory_link_target(
        "glossary:commit-ish",
        notes=notes,
        scoped_webs=scoped_webs,
    )

    assert isinstance(target, MemoryStrandLinkTarget)
    assert target.address == "glossary:stitch"
    assert target.strand.slug == "stitch"
    assert target.scope == "project"


def test_resolve_web_slug_target_form(tmp_path: Path) -> None:
    _seed_memory(tmp_path)
    notes, scoped_webs = _universe(tmp_path)

    target = resolve_memory_link_target(
        "decisions/single-turn-agents",
        notes=notes,
        scoped_webs=scoped_webs,
    )

    assert isinstance(target, MemoryStrandLinkTarget)
    assert target.address == "decisions:single-turn-agents"
    assert target.strand.keyword == "Agents Are Single-Turn"


def test_resolve_flat_note_markdown_target(tmp_path: Path) -> None:
    _seed_memory(tmp_path)
    notes, scoped_webs = _universe(tmp_path)

    target = resolve_memory_link_target(
        "symvision.md",
        notes=notes,
        scoped_webs=scoped_webs,
    )

    assert isinstance(target, MemoryNoteLinkTarget)
    assert target.address == "symvision.md"
    assert target.note.description == "Symvision."


def test_resolve_bare_token_prefers_source_strand_web(tmp_path: Path) -> None:
    _seed_memory(tmp_path)
    notes, scoped_webs = _universe(tmp_path)
    glossary = next(web for web in scoped_webs if web.slug == "glossary")
    source = resolve_memory_strand(glossary.web, "stitch")

    target = resolve_memory_link_target(
        "patch",
        notes=notes,
        scoped_webs=scoped_webs,
        source_strand=source,
    )

    assert isinstance(target, MemoryStrandLinkTarget)
    assert target.address == "glossary:patch"


def test_resolve_bare_token_falls_back_to_note_stem_then_web_descriptor(
    tmp_path: Path,
) -> None:
    _seed_memory(tmp_path)
    notes, scoped_webs = _universe(tmp_path)

    note_target = resolve_memory_link_target(
        "symvision",
        notes=notes,
        scoped_webs=scoped_webs,
    )
    descriptor_target = resolve_memory_link_target(
        "glossary",
        notes=notes,
        scoped_webs=scoped_webs,
    )

    assert isinstance(note_target, MemoryNoteLinkTarget)
    assert note_target.address == "symvision.md"
    assert isinstance(descriptor_target, MemoryWebDescriptorLinkTarget)
    assert descriptor_target.address == "glossary"
    assert descriptor_target.relative_path == "sase/memory/glossary.md"


def test_resolve_drops_self_links(tmp_path: Path) -> None:
    _seed_memory(tmp_path)
    notes, scoped_webs = _universe(tmp_path)
    glossary = next(web for web in scoped_webs if web.slug == "glossary")
    source_strand = resolve_memory_strand(glossary.web, "stitch")
    source_note = next(
        note for note in notes if note.relative_path.endswith("symvision.md")
    )

    assert (
        resolve_memory_link_target(
            "stitch",
            notes=notes,
            scoped_webs=scoped_webs,
            source_strand=source_strand,
        )
        is None
    )
    assert (
        resolve_memory_link_target(
            "symvision",
            notes=notes,
            scoped_webs=scoped_webs,
            source_note=source_note,
        )
        is None
    )


def test_unresolved_targets_carry_near_miss_candidates(tmp_path: Path) -> None:
    _seed_memory(tmp_path)
    notes, scoped_webs = _universe(tmp_path)

    target = resolve_memory_link_target(
        "glossary/stit",
        notes=notes,
        scoped_webs=scoped_webs,
    )

    assert isinstance(target, UnresolvedMemoryLinkTarget)
    assert "glossary:stitch" in target.candidates


def test_unresolved_targets_allow_no_candidates(tmp_path: Path) -> None:
    _seed_memory(tmp_path)
    notes, scoped_webs = _universe(tmp_path)

    target = resolve_memory_link_target(
        "does-not-exist",
        notes=notes,
        scoped_webs=scoped_webs,
    )

    assert isinstance(target, UnresolvedMemoryLinkTarget)
    assert target.candidates == ()
