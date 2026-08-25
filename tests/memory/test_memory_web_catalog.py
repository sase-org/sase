"""Tests for the strand-backed glossary catalog helpers in ``memory.web.catalog``."""

from __future__ import annotations

from pathlib import Path

from sase.core.glossary_facade import GlossarySource
from sase.memory.web.catalog import (
    find_memory_web,
    glossary_dual_source_diagnostic,
    memory_web_glossary_entries,
    memory_web_source_signature,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _descriptor() -> str:
    return (
        "---\n"
        "type: core\n"
        "parent: AGENTS.md\n"
        "web: true\n"
        "roster: inline\n"
        "roster_label: GLOSSARY TERMS\n"
        "---\n\n"
        "Glossary descriptor.\n"
    )


def _strand(
    *,
    keyword: str | None = "Agent Hood",
    aliases: str = "aliases: [hood]\n",
    body: str = "A named container.\n",
) -> str:
    keyword_line = "" if keyword is None else f"keyword: {keyword}\n"
    return f"---\n{keyword_line}{aliases}---\n\n{body}"


def _write_glossary_web(root: Path, *, filename: str = "agent-hood.md") -> Path:
    _write(root / "sase" / "memory" / "glossary.md", _descriptor())
    strand_path = root / "sase" / "memory" / "glossary" / filename
    _write(strand_path, _strand())
    return strand_path


def test_find_memory_web_matches_slug_and_returns_none_for_unknown(
    tmp_path: Path,
) -> None:
    _write_glossary_web(tmp_path)

    web = find_memory_web(tmp_path, "glossary")

    assert web is not None
    assert web.slug == "glossary"
    assert find_memory_web(tmp_path, "decisions") is None


def test_memory_web_glossary_entries_carries_source_path_and_keyword_range(
    tmp_path: Path,
) -> None:
    strand_path = _write_glossary_web(tmp_path)
    web = find_memory_web(tmp_path, "glossary")
    assert web is not None

    (entry,) = memory_web_glossary_entries(web)

    assert entry.term == "Agent Hood"
    assert entry.aliases == ("hood",)
    assert isinstance(entry.source, GlossarySource)
    assert entry.source.source_path == str(strand_path)
    assert entry.source.key_path == ()
    assert entry.source.keyword_range == {
        "start": {"line": 1, "character": 9},
        "end": {"line": 1, "character": 19},
    }


def test_memory_web_glossary_entries_falls_back_to_first_body_line(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "sase" / "memory" / "glossary.md", _descriptor())
    strand_path = tmp_path / "sase" / "memory" / "glossary" / "agent-hood.md"
    _write(strand_path, _strand(keyword=None, aliases=""))
    web = find_memory_web(tmp_path, "glossary")
    assert web is not None
    (strand,) = web.strands

    (entry,) = memory_web_glossary_entries(web)

    assert entry.term == "Agent Hood"
    body_line = strand.raw_text.count("\n", 0, strand.body_start)
    assert isinstance(entry.source, GlossarySource)
    assert entry.source.keyword_range == {
        "start": {"line": body_line, "character": 0},
        "end": {"line": body_line, "character": len("A named container.")},
    }


def test_memory_web_source_signature_changes_on_strand_edit(tmp_path: Path) -> None:
    strand_path = _write_glossary_web(tmp_path)
    web = find_memory_web(tmp_path, "glossary")
    assert web is not None
    before = memory_web_source_signature(web)

    _write(strand_path, _strand(body="A named, rootless container for agents.\n"))
    web_after_edit = find_memory_web(tmp_path, "glossary")
    assert web_after_edit is not None
    after = memory_web_source_signature(web_after_edit)

    assert after.size != before.size


def test_memory_web_source_signature_changes_when_strand_added_or_removed(
    tmp_path: Path,
) -> None:
    strand_path = _write_glossary_web(tmp_path)
    web = find_memory_web(tmp_path, "glossary")
    assert web is not None
    one_strand = memory_web_source_signature(web)

    second_strand = tmp_path / "sase" / "memory" / "glossary" / "artifact-ref.md"
    _write(
        second_strand,
        _strand(keyword="Artifact Reference", aliases="aliases: [ref]\n"),
    )
    web_with_two = find_memory_web(tmp_path, "glossary")
    assert web_with_two is not None
    two_strands = memory_web_source_signature(web_with_two)
    assert two_strands.size != one_strand.size

    strand_path.unlink()
    web_with_one_again = find_memory_web(tmp_path, "glossary")
    assert web_with_one_again is not None
    one_strand_again = memory_web_source_signature(web_with_one_again)
    assert one_strand_again.size != two_strands.size


def test_glossary_dual_source_diagnostic_only_fires_when_both_present() -> None:
    assert glossary_dual_source_diagnostic(has_web=False, config_declared=False) is None
    assert glossary_dual_source_diagnostic(has_web=True, config_declared=False) is None
    assert glossary_dual_source_diagnostic(has_web=False, config_declared=True) is None

    message = glossary_dual_source_diagnostic(has_web=True, config_declared=True)

    assert message is not None
    assert "sase memory web migrate glossary" in message
