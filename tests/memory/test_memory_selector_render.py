"""Tests for Markdown rendering of resolved ``memory read``/``show`` batches."""

from __future__ import annotations

from pathlib import Path

from sase.memory.selector import resolve_memory_selector_batch
from sase.memory.selector_render import memory_selector_batch_markdown


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


def _resolve(root: Path, selectors: list[str]):
    return resolve_memory_selector_batch(
        selectors, project_root=root, home_root=root / "home"
    )


def test_single_note_batch_markdown_is_unchanged_and_unlabeled(tmp_path: Path) -> None:
    _write(tmp_path / "sase" / "memory" / "foo.md", _note("# Foo body\n"))

    batch = _resolve(tmp_path, ["foo.md"])

    assert memory_selector_batch_markdown(batch) == "# Foo body\n"


def test_multi_note_batch_markdown_labels_each_note_before_its_body(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "sase" / "memory" / "first.md", _note("# First body\n"))
    _write(tmp_path / "sase" / "memory" / "second.md", _note("# Second body\n"))

    batch = _resolve(tmp_path, ["first.md", "second.md"])

    output = memory_selector_batch_markdown(batch)
    assert "MEMORY FILE: first.md" in output
    assert "MEMORY FILE: second.md" in output
    first_header = output.index("MEMORY FILE: first.md")
    first_body = output.index("# First body")
    second_header = output.index("MEMORY FILE: second.md")
    second_body = output.index("# Second body")
    assert first_header < first_body < second_header < second_body


def test_mixed_note_and_web_batch_labels_note_and_keeps_web_header(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "sase" / "memory" / "foo.md", _note("# Foo body\n"))
    _seed_glossary_web(tmp_path)

    batch = _resolve(tmp_path, ["foo.md", "glossary:stitch"])

    output = memory_selector_batch_markdown(batch)
    assert "MEMORY FILE: foo.md" in output
    assert "MEMORY WEB: glossary" in output
    assert output.index("MEMORY FILE: foo.md") < output.index("# Foo body")


def test_note_section_retains_children_listing_beneath_its_header(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "sase" / "memory" / "parent.md", _note("# Parent body\n"))
    _write(
        tmp_path / "sase" / "memory" / "child.md",
        _note("# Child body\n", description="A child note.").replace(
            "parent: AGENTS.md", "parent: parent.md"
        ),
    )

    batch = _resolve(tmp_path, ["parent.md", "child.md"])

    output = memory_selector_batch_markdown(batch)
    header = output.index("MEMORY FILE: parent.md")
    children_section = output.index("## Children")
    child_entry = output.index("child.md", children_section)
    assert header < children_section < child_entry
