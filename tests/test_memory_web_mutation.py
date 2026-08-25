"""Create/delete tests for the memory-web strand mutation engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.memory.web import (
    MemoryConflictError,
    MemoryStrandMutationError,
    MemoryStrandValidationError,
    create_memory_strand,
    delete_memory_strand,
    discover_memory_webs,
    memory_strand_digest,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _descriptor(*, roster: str = "inline", body: str = "Descriptor body.\n") -> str:
    return (
        "---\n"
        "type: core\n"
        "parent: AGENTS.md\n"
        "web: true\n"
        f"roster: {roster}\n"
        "roster_label: TERMS\n"
        "---\n\n"
        f"{body}"
    )


def _strand(
    *,
    keyword: str = "Alpha Term",
    aliases: str = "aliases: [alpha-alias]\n",
    summary: str = "summary: First term.\n",
    body: str = "Strand body.\n",
) -> str:
    return f"---\nkeyword: {keyword}\n{aliases}{summary}---\n\n{body}"


def _seed_web(tmp_path: Path) -> None:
    _write(tmp_path / "sase" / "memory" / "terms.md", _descriptor())
    _write(tmp_path / "sase" / "memory" / "terms" / "alpha.md", _strand())


def test_create_writes_strand_and_updates_descriptor_roster(tmp_path: Path) -> None:
    _seed_web(tmp_path)

    outcome = create_memory_strand(
        scope_key="demo",
        content_root=tmp_path,
        web_slug="terms",
        slug="beta",
        keyword="Beta Term",
        aliases=["beta-alias"],
        summary="Second term.",
        metadata={"origin": "test"},
        body="Beta body.\n",
    )

    assert outcome.web_slug == "terms"
    assert outcome.slug == "beta"
    assert outcome.keyword == "Beta Term"
    assert outcome.aliases == ("beta-alias",)
    assert outcome.summary == "Second term."
    assert outcome.metadata == {"origin": "test"}
    assert outcome.relative_path == "sase/memory/terms/beta.md"

    strand_path = tmp_path / "sase" / "memory" / "terms" / "beta.md"
    assert strand_path.is_file()
    strand_text = strand_path.read_text(encoding="utf-8")
    assert "keyword: Beta Term" in strand_text
    assert "beta-alias" in strand_text
    assert "Second term." in strand_text
    assert strand_text.endswith("Beta body.\n")

    descriptor_text = (tmp_path / "sase" / "memory" / "terms.md").read_text(
        encoding="utf-8"
    )
    assert "Beta Term" in descriptor_text
    assert "beta-alias" in descriptor_text

    (web,) = discover_memory_webs(tmp_path).webs
    slugs = {strand.slug for strand in web.strands}
    assert slugs == {"alpha", "beta"}
    (new_strand,) = [strand for strand in web.strands if strand.slug == "beta"]
    assert new_strand.keyword == "Beta Term"
    assert new_strand.aliases == ("beta-alias",)
    assert new_strand.summary == "Second term."
    assert new_strand.metadata == {"origin": "test"}


def test_create_defaults_keyword_from_slug_when_omitted(tmp_path: Path) -> None:
    _seed_web(tmp_path)

    outcome = create_memory_strand(
        scope_key="demo",
        content_root=tmp_path,
        web_slug="terms",
        slug="agent-hood",
        body="An agent hood is a group of agents named alike.\n",
    )

    assert outcome.keyword == "Agent Hood"
    assert outcome.aliases == ()
    assert outcome.summary is None
    assert outcome.metadata == {}


def test_create_rejects_empty_body_that_would_break_the_roster(
    tmp_path: Path,
) -> None:
    _seed_web(tmp_path)

    with pytest.raises(MemoryStrandMutationError, match="invalid"):
        create_memory_strand(
            scope_key="demo",
            content_root=tmp_path,
            web_slug="terms",
            slug="beta",
            keyword="Beta Term",
        )

    assert not (tmp_path / "sase" / "memory" / "terms" / "beta.md").exists()
    descriptor_text = (tmp_path / "sase" / "memory" / "terms.md").read_text(
        encoding="utf-8"
    )
    assert "Beta Term" not in descriptor_text


@pytest.mark.parametrize(
    ("slug", "keyword", "aliases"),
    [
        ("alpha", "Fresh Keyword", ()),
        ("fresh-slug", "Alpha Term", ()),
        ("fresh-slug", "Fresh Keyword", ("alpha-alias",)),
    ],
)
def test_create_rejects_collision_with_existing_strand(
    tmp_path: Path, slug: str, keyword: str, aliases: tuple[str, ...]
) -> None:
    _seed_web(tmp_path)

    with pytest.raises(MemoryStrandValidationError):
        create_memory_strand(
            scope_key="demo",
            content_root=tmp_path,
            web_slug="terms",
            slug=slug,
            keyword=keyword,
            aliases=aliases,
        )

    assert not (tmp_path / "sase" / "memory" / "terms" / "fresh-slug.md").exists()


def test_create_refuses_unknown_web(tmp_path: Path) -> None:
    _seed_web(tmp_path)

    with pytest.raises(MemoryStrandMutationError, match="does not exist"):
        create_memory_strand(
            scope_key="demo",
            content_root=tmp_path,
            web_slug="missing",
            slug="beta",
        )


def test_delete_removes_strand_backs_up_and_updates_descriptor(
    tmp_path: Path,
) -> None:
    _seed_web(tmp_path)
    strand_path = tmp_path / "sase" / "memory" / "terms" / "alpha.md"
    original = strand_path.read_bytes()

    outcome = delete_memory_strand(
        scope_key="demo",
        content_root=tmp_path,
        web_slug="terms",
        slug="alpha",
        expected_digest=memory_strand_digest(original),
    )

    assert not strand_path.exists()
    assert outcome.backup_path is not None
    assert outcome.backup_path.is_file()
    assert outcome.backup_path.read_bytes() == original
    assert outcome.backup_path.parent == tmp_path / ".sase" / "memory-backups"
    assert outcome.backup_path.name.startswith("terms-alpha-")

    descriptor_text = (tmp_path / "sase" / "memory" / "terms.md").read_text(
        encoding="utf-8"
    )
    assert "Alpha Term" not in descriptor_text

    (web,) = discover_memory_webs(tmp_path).webs
    assert web.strands == ()


def test_delete_raises_on_stale_digest_and_does_not_delete(tmp_path: Path) -> None:
    _seed_web(tmp_path)
    strand_path = tmp_path / "sase" / "memory" / "terms" / "alpha.md"
    stale = memory_strand_digest(strand_path.read_bytes())
    strand_path.write_text(
        strand_path.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8"
    )

    with pytest.raises(MemoryConflictError, match="reload and retry"):
        delete_memory_strand(
            scope_key="demo",
            content_root=tmp_path,
            web_slug="terms",
            slug="alpha",
            expected_digest=stale,
        )

    assert strand_path.is_file()
    assert "changed" in strand_path.read_text(encoding="utf-8")


def test_delete_raises_clear_error_for_missing_slug(tmp_path: Path) -> None:
    _seed_web(tmp_path)

    with pytest.raises(MemoryStrandMutationError, match="does not exist"):
        delete_memory_strand(
            scope_key="demo",
            content_root=tmp_path,
            web_slug="terms",
            slug="does-not-exist",
            expected_digest="0" * 64,
        )
