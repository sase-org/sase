"""Tests for variadic ``sase memory read``/``show`` selector resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

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
