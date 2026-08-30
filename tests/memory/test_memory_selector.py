"""Tests for variadic ``sase memory read``/``show`` selector resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.memory.link_resolve import MemoryStrandLinkTarget
from sase.memory.selector import _MemorySelectorError, resolve_memory_selector_batch


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _note(body: str = "# Body\n", *, description: str = "A note.") -> str:
    return f"---\ntype: reference\nparent: AGENTS.md\ndescription: {description}\n---\n{body}"


def _descriptor(
    *, note_type: str = "core", roster: str = "inline", closure: str = "none"
) -> str:
    return (
        "---\n"
        f"type: {note_type}\n"
        "web: true\n"
        f"roster: {roster}\n"
        f"closure: {closure}\n"
        "---\n\nPreamble.\n"
    )


def _seed_glossary_web(root: Path, *, closure: str = "none") -> None:
    _write(root / "sase" / "memory" / "glossary.md", _descriptor(closure=closure))
    _write(
        root / "sase" / "memory" / "glossary" / "stitch.md",
        "---\naliases: [commit-ish]\nsummary: A change record.\n---\n"
        "A Stitch mentions Patch inside its body.\n",
    )
    _write(
        root / "sase" / "memory" / "glossary" / "patch.md",
        "---\nsummary: A proposed change.\n---\nA Patch precedes a Stitch.\n",
    )


def test_single_note_selector_is_flagged_single_note(tmp_path: Path) -> None:
    _write(tmp_path / "sase" / "memory" / "foo.md", _note())

    batch = resolve_memory_selector_batch(
        ["foo.md"], project_root=tmp_path, home_root=tmp_path / "home"
    )

    assert batch.is_single_note
    assert batch.kind == "note"
    assert batch.notes[0].content.path.canonical_path == "foo.md"


def test_bare_web_selector_reads_every_strand(tmp_path: Path) -> None:
    _seed_glossary_web(tmp_path)

    batch = resolve_memory_selector_batch(
        ["glossary"], project_root=tmp_path, home_root=tmp_path / "home"
    )

    assert batch.kind == "web"
    (section,) = batch.web_sections
    assert {node.strand.slug for node in section.nodes} == {"stitch", "patch"}
    assert all(node.origin == "requested" for node in section.nodes)


def test_strand_selector_with_closure_none_does_not_expand(tmp_path: Path) -> None:
    _seed_glossary_web(tmp_path, closure="none")

    batch = resolve_memory_selector_batch(
        ["glossary:stitch"], project_root=tmp_path, home_root=tmp_path / "home"
    )

    (section,) = batch.web_sections
    assert [node.strand.slug for node in section.nodes] == ["stitch"]
    assert batch.kind == "strand"


def test_strand_selector_with_closure_mentions_expands_to_related(
    tmp_path: Path,
) -> None:
    _seed_glossary_web(tmp_path, closure="mentions")

    batch = resolve_memory_selector_batch(
        ["glossary:stitch"], project_root=tmp_path, home_root=tmp_path / "home"
    )

    (section,) = batch.web_sections
    slugs = {node.strand.slug: node.origin for node in section.nodes}
    assert slugs == {"stitch": "requested", "patch": "related"}


def test_mixed_note_and_strand_batch_resolves_both(tmp_path: Path) -> None:
    _write(tmp_path / "sase" / "memory" / "foo.md", _note())
    _seed_glossary_web(tmp_path)

    batch = resolve_memory_selector_batch(
        ["glossary:stitch", "foo.md"],
        project_root=tmp_path,
        home_root=tmp_path / "home",
    )

    assert len(batch.notes) == 1
    assert len(batch.web_sections) == 1
    assert batch.selectors == ("glossary:stitch", "foo.md")
    assert not batch.is_single_note


def test_unknown_strand_selector_fails_whole_batch_atomically(tmp_path: Path) -> None:
    _write(tmp_path / "sase" / "memory" / "foo.md", _note())
    _seed_glossary_web(tmp_path)

    with pytest.raises(_MemorySelectorError, match="unknown memory strand"):
        resolve_memory_selector_batch(
            ["foo.md", "glossary:bogus"],
            project_root=tmp_path,
            home_root=tmp_path / "home",
        )


def test_unknown_web_selector_raises(tmp_path: Path) -> None:
    with pytest.raises(_MemorySelectorError, match="unknown memory web"):
        resolve_memory_selector_batch(
            ["bogus"], project_root=tmp_path, home_root=tmp_path / "home"
        )


def test_web_descriptor_cannot_be_read_but_strands_can(tmp_path: Path) -> None:
    _seed_glossary_web(tmp_path)

    with pytest.raises(_MemorySelectorError) as exc:
        resolve_memory_selector_batch(
            ["glossary.md"], project_root=tmp_path, home_root=tmp_path / "home"
        )
    message = str(exc.value)
    assert "always-loaded memory web descriptor" in message
    assert "sase memory read glossary:<keyword>" in message

    # The descriptor is refused, but its strands are not.
    batch = resolve_memory_selector_batch(
        ["glossary:stitch"], project_root=tmp_path, home_root=tmp_path / "home"
    )
    assert batch.web_sections


def test_nested_note_selector_suggests_web_keyword_form(tmp_path: Path) -> None:
    _seed_glossary_web(tmp_path)

    with pytest.raises(_MemorySelectorError, match="glossary:stitch"):
        resolve_memory_selector_batch(
            ["glossary/stitch.md"],
            project_root=tmp_path,
            home_root=tmp_path / "home",
        )


def test_empty_selector_batch_raises() -> None:
    with pytest.raises(_MemorySelectorError, match="at least one"):
        resolve_memory_selector_batch([])


# --- authored [[...]]/![[...]] link closure integration -------------------


def _link_descriptor(*, description: str = "A web.") -> str:
    """A descriptor with no ``closure``/``link_reference`` override.

    Strands default to ``link_reference: explicit`` and
    ``link_rendering: reference``, so ``[[target]]`` stays a reference and
    only ``![[target]]`` forces inline expansion.
    """
    return (
        "---\nweb: true\n"
        f"description: {description}\n"
        "roster: inline\n---\n\nPreamble.\n"
    )


def _seed_decisions_web(root: Path) -> None:
    _write(root / "sase" / "memory" / "decisions.md", _link_descriptor())
    _write(
        root / "sase" / "memory" / "decisions" / "gates-never-block.md",
        "---\nkeyword: A Gate Never Blocks\nsummary: Gate summary.\n---\n"
        "See ![[decisions/single-turn-agents]] for more.\n",
    )
    _write(
        root / "sase" / "memory" / "decisions" / "single-turn-agents.md",
        "---\nkeyword: Agents Are Single-Turn\nsummary: Turn summary.\n---\n"
        "A run is one turn.\n",
    )


def test_same_web_inline_link_expands_into_closure(tmp_path: Path) -> None:
    _seed_decisions_web(tmp_path)

    batch = resolve_memory_selector_batch(
        ["decisions:gates-never-block"],
        project_root=tmp_path,
        home_root=tmp_path / "home",
    )

    (section,) = batch.web_sections
    slugs = {node.strand.slug: node.origin for node in section.nodes}
    assert slugs == {
        "gates-never-block": "requested",
        "single-turn-agents": "related",
    }
    related = next(n for n in section.nodes if n.strand.slug == "single-turn-agents")
    assert related.referrer is not None
    term, _matched_text, kind = related.referrer
    assert kind == "link"
    assert term == "A Gate Never Blocks"
    assert section.resolved_links == ()


def test_reference_style_link_does_not_expand_but_is_collected(tmp_path: Path) -> None:
    _write(tmp_path / "sase" / "memory" / "decisions.md", _link_descriptor())
    _write(
        tmp_path / "sase" / "memory" / "decisions" / "gates-never-block.md",
        "---\nkeyword: A Gate Never Blocks\nsummary: Gate summary.\n---\n"
        "See [[decisions/single-turn-agents]] for more.\n",
    )
    _write(
        tmp_path / "sase" / "memory" / "decisions" / "single-turn-agents.md",
        "---\nkeyword: Agents Are Single-Turn\nsummary: Turn summary.\n---\n"
        "A run is one turn.\n",
    )

    batch = resolve_memory_selector_batch(
        ["decisions:gates-never-block"],
        project_root=tmp_path,
        home_root=tmp_path / "home",
    )

    (section,) = batch.web_sections
    assert [node.strand.slug for node in section.nodes] == ["gates-never-block"]
    (link,) = section.resolved_links
    assert link.kind == "strand"
    assert link.address == "decisions:single-turn-agents"


def test_mixed_inline_and_reference_links_in_one_body(tmp_path: Path) -> None:
    _write(tmp_path / "sase" / "memory" / "decisions.md", _link_descriptor())
    _write(
        tmp_path / "sase" / "memory" / "decisions" / "alpha.md",
        "---\nkeyword: Alpha\nsummary: Alpha.\n---\n"
        "Inline ![[decisions/beta]] and reference [[decisions/gamma]].\n",
    )
    _write(
        tmp_path / "sase" / "memory" / "decisions" / "beta.md",
        "---\nkeyword: Beta\nsummary: Beta.\n---\nLeaf.\n",
    )
    _write(
        tmp_path / "sase" / "memory" / "decisions" / "gamma.md",
        "---\nkeyword: Gamma\nsummary: Gamma.\n---\nLeaf.\n",
    )

    batch = resolve_memory_selector_batch(
        ["decisions:alpha"], project_root=tmp_path, home_root=tmp_path / "home"
    )

    (section,) = batch.web_sections
    assert {node.strand.slug for node in section.nodes} == {"alpha", "beta"}
    (link,) = section.resolved_links
    assert isinstance(link, MemoryStrandLinkTarget)
    assert link.address == "decisions:gamma"
    alpha = next(node for node in section.nodes if node.strand.slug == "alpha")
    kinds = {item.target.address: item.kind for item in alpha.links}
    assert kinds == {"decisions:beta": "inline", "decisions:gamma": "reference"}


def test_depth_zero_treats_every_link_as_reference(tmp_path: Path) -> None:
    _seed_decisions_web(tmp_path)

    batch = resolve_memory_selector_batch(
        ["decisions:gates-never-block"],
        project_root=tmp_path,
        home_root=tmp_path / "home",
        depth=0,
    )

    (section,) = batch.web_sections
    assert [node.strand.slug for node in section.nodes] == ["gates-never-block"]
    (link,) = section.resolved_links
    assert isinstance(link, MemoryStrandLinkTarget)
    assert link.address == "decisions:single-turn-agents"


def test_depth_limit_truncates_chained_inline_links(tmp_path: Path) -> None:
    _write(tmp_path / "sase" / "memory" / "decisions.md", _link_descriptor())
    _write(
        tmp_path / "sase" / "memory" / "decisions" / "alpha.md",
        "---\nkeyword: Alpha\nsummary: Alpha.\n---\nSee ![[decisions/beta]].\n",
    )
    _write(
        tmp_path / "sase" / "memory" / "decisions" / "beta.md",
        "---\nkeyword: Beta\nsummary: Beta.\n---\nSee ![[decisions/gamma]].\n",
    )
    _write(
        tmp_path / "sase" / "memory" / "decisions" / "gamma.md",
        "---\nkeyword: Gamma\nsummary: Gamma.\n---\nLeaf.\n",
    )

    batch = resolve_memory_selector_batch(
        ["decisions:alpha"],
        project_root=tmp_path,
        home_root=tmp_path / "home",
        depth=1,
    )

    (section,) = batch.web_sections
    assert [node.strand.slug for node in section.nodes] == ["alpha", "beta"]
    assert section.truncated is True
    (link,) = section.resolved_links
    assert isinstance(link, MemoryStrandLinkTarget)
    assert link.address == "decisions:gamma"


def test_strand_link_reference_none_disables_authored_links(tmp_path: Path) -> None:
    _write(tmp_path / "sase" / "memory" / "decisions.md", _link_descriptor())
    _write(
        tmp_path / "sase" / "memory" / "decisions" / "gates-never-block.md",
        "---\nkeyword: A Gate Never Blocks\nsummary: Gate summary.\n"
        "link_reference: none\n---\n"
        "See ![[decisions/single-turn-agents]] for more.\n",
    )
    _write(
        tmp_path / "sase" / "memory" / "decisions" / "single-turn-agents.md",
        "---\nkeyword: Agents Are Single-Turn\nsummary: Turn summary.\n---\n"
        "A run is one turn.\n",
    )

    batch = resolve_memory_selector_batch(
        ["decisions:gates-never-block"],
        project_root=tmp_path,
        home_root=tmp_path / "home",
    )

    (section,) = batch.web_sections
    assert [node.strand.slug for node in section.nodes] == ["gates-never-block"]
    assert section.resolved_links == ()


def test_unresolved_link_is_collected_with_no_candidates(tmp_path: Path) -> None:
    _write(tmp_path / "sase" / "memory" / "decisions.md", _link_descriptor())
    _write(
        tmp_path / "sase" / "memory" / "decisions" / "alpha.md",
        "---\nkeyword: Alpha\nsummary: Alpha.\n---\nSee [[does-not-exist]].\n",
    )

    batch = resolve_memory_selector_batch(
        ["decisions:alpha"], project_root=tmp_path, home_root=tmp_path / "home"
    )

    (section,) = batch.web_sections
    (link,) = section.resolved_links
    assert link.kind == "unresolved"
    assert link.raw == "does-not-exist"


def test_cross_web_inline_link_adds_extra_root_section(tmp_path: Path) -> None:
    _seed_glossary_web(tmp_path, closure="none")
    _write(tmp_path / "sase" / "memory" / "decisions.md", _link_descriptor())
    _write(
        tmp_path / "sase" / "memory" / "decisions" / "alpha.md",
        "---\nkeyword: Alpha\nsummary: Alpha.\n---\nSee ![[glossary:stitch]] for context.\n",
    )

    batch = resolve_memory_selector_batch(
        ["decisions:alpha"], project_root=tmp_path, home_root=tmp_path / "home"
    )

    sections_by_slug = {section.web.slug: section for section in batch.web_sections}
    assert set(sections_by_slug) == {"decisions", "glossary"}
    glossary_section = sections_by_slug["glossary"]
    assert [node.strand.slug for node in glossary_section.nodes] == ["stitch"]
    (node,) = glossary_section.nodes
    assert node.origin == "related"
    assert node.referrer is not None
    assert node.referrer[2] == "link"


def test_flat_note_links_are_always_collected_as_references(tmp_path: Path) -> None:
    _write(tmp_path / "sase" / "memory" / "decisions.md", _link_descriptor())
    _write(
        tmp_path / "sase" / "memory" / "decisions" / "single-turn-agents.md",
        "---\nkeyword: Agents Are Single-Turn\nsummary: Turn summary.\n---\n"
        "A run is one turn.\n",
    )
    _write(
        tmp_path / "sase" / "memory" / "foo.md",
        _note(
            body="# Body\n"
            "See ![[decisions:single-turn-agents]] and [[does-not-exist]].\n"
        ),
    )

    batch = resolve_memory_selector_batch(
        ["foo.md"], project_root=tmp_path, home_root=tmp_path / "home"
    )

    (note,) = batch.notes
    kinds = {link.kind for link in note.resolved_links}
    assert kinds == {"strand", "unresolved"}
