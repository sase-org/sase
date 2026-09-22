"""Tests for batch-level Markdown rendering of memory selector batches."""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path

from rich.console import Console

from sase.memory.selector import resolve_memory_selector_batch
from sase.memory.selector_render import (
    memory_selector_batch_markdown,
    render_memory_selector_batch,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _note(body: str = "# Body\n", *, description: str = "A note.") -> str:
    return f"---\ntype: reference\nparent: AGENTS.md\ndescription: {description}\n---\n{body}"


def _descriptor(
    *,
    note_type: str = "core",
    roster: str = "inline",
    link_reference: str | None = None,
    closure: str | None = None,
) -> str:
    extra = ""
    if closure is not None:
        extra += f"closure: {closure}\n"
    elif link_reference is not None:
        extra += f"link_reference: {link_reference}\n"
    return (
        "---\n"
        f"type: {note_type}\n"
        "web: true\n"
        f"roster: {roster}\n"
        f"{extra}"
        "---\n\nPreamble.\n"
    )


def _seed_glossary_web(
    root: Path, *, link_reference: str | None = None, closure: str | None = None
) -> None:
    _write(
        root / "sase" / "memory" / "glossary.md",
        _descriptor(link_reference=link_reference, closure=closure),
    )
    _write(
        root / "sase" / "memory" / "glossary" / "stitch.md",
        "---\naliases: [commit-ish]\nsummary: A change record.\n---\n"
        "A Stitch mentions Patch inside its body.\n",
    )


def _resolve(root: Path, selectors: list[str], *, depth: int | None = None):
    return resolve_memory_selector_batch(
        selectors, project_root=root, home_root=root / "home", depth=depth
    )


def _json_payload(batch) -> dict:
    buf = StringIO()
    with redirect_stdout(buf):
        render_memory_selector_batch(batch, output_format="json")
    return json.loads(buf.getvalue())


def _rich_text(batch) -> str:
    output = StringIO()
    console = Console(file=output, force_terminal=False, color_system=None, width=160)
    render_memory_selector_batch(batch, output_format="rich", console=console)
    return output.getvalue()


def _seed_decisions_web(root: Path) -> None:
    _write(
        root / "sase" / "memory" / "decisions.md",
        "---\nweb: true\ndescription: Decision records.\nroster: list\n---\n\nPreamble.\n",
    )
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


_LINKED_INTRO = (
    "The below memory files are linked from this one. Read one with your "
    "`/sase_memory_read`\n"
    "skill; do not open the file directly."
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
    assert output == (
        "\n---------- MEMORY FILE: first.md\n"
        "\n"
        "# First body\n"
        "\n"
        "---------- MEMORY FILE: second.md\n"
        "\n"
        "# Second body\n"
    )


def test_mixed_note_and_web_batch_labels_note_and_keeps_web_header(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "sase" / "memory" / "foo.md", _note("# Foo body\n"))
    _seed_glossary_web(tmp_path)

    batch = _resolve(tmp_path, ["foo.md", "glossary:stitch"])

    output = memory_selector_batch_markdown(batch)
    assert output == (
        "\n---------- MEMORY FILE: foo.md\n"
        "\n"
        "# Foo body\n"
        "\n"
        "---------- MEMORY WEB: glossary\n"
        "\n"
        "# Stitch\n"
        "\n"
        "*Requested · project*\n"
        "\n"
        "aka commit-ish\n"
        "\n"
        "A Stitch mentions Patch inside its body.\n"
    )


def test_note_section_suppresses_child_listing_when_child_body_is_rendered(
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
    parent_header = "---------- MEMORY FILE: parent.md"
    child_header = "---------- MEMORY FILE: child.md"
    assert output.startswith(f"\n{parent_header}\n\n")
    parent_header_at = output.index(parent_header)
    child_header_at = output.index(child_header)
    assert parent_header_at < child_header_at
    assert "## Children" not in output


def test_note_markdown_appends_numbered_linked_references(tmp_path: Path) -> None:
    _seed_decisions_web(tmp_path)
    _write(
        tmp_path / "sase" / "memory" / "foo.md",
        _note("# Body\nSee [[decisions:single-turn-agents]].\n"),
    )

    output = memory_selector_batch_markdown(_resolve(tmp_path, ["foo.md"]))

    assert output == (
        "# Body\n"
        "See [[decisions:single-turn-agents]].\n"
        "\n"
        "## Linked References\n"
        "\n"
        f"{_LINKED_INTRO}\n"
        "\n"
        "### 1. `decisions:single-turn-agents`\n"
        "\n"
        "**Agents Are Single-Turn** — Turn summary.\n"
    )


def test_note_markdown_places_linked_references_after_children(tmp_path: Path) -> None:
    _seed_decisions_web(tmp_path)
    _write(
        tmp_path / "sase" / "memory" / "parent.md",
        _note("# Parent\nSee [[decisions:single-turn-agents]].\n"),
    )
    _write(
        tmp_path / "sase" / "memory" / "child.md",
        _note("# Child body\n", description="A child note.").replace(
            "parent: AGENTS.md", "parent: parent.md"
        ),
    )

    output = memory_selector_batch_markdown(_resolve(tmp_path, ["parent.md"]))

    children_at = output.index("## Children")
    linked_at = output.index("## Linked References")
    assert children_at < linked_at
    assert "### 1. `decisions:single-turn-agents`" in output


def test_linked_child_references_replace_complete_children_listing(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "sase" / "memory" / "parent.md",
        _note("# Parent\nSee [[alpha]] and [[beta]].\n"),
    )
    _write(
        tmp_path / "sase" / "memory" / "alpha.md",
        _note("# Alpha\n", description="Alpha child.").replace(
            "parent: AGENTS.md", "parent: parent.md"
        ),
    )
    _write(
        tmp_path / "sase" / "memory" / "beta.md",
        _note("# Beta\n", description="Beta child.").replace(
            "parent: AGENTS.md", "parent: parent.md"
        ),
    )

    batch = _resolve(tmp_path, ["parent.md"])
    output = memory_selector_batch_markdown(batch)
    payload = _json_payload(batch)
    rich = _rich_text(batch)

    assert "## Children" not in output
    assert "## Linked References" in output
    assert "### 1. `alpha.md`" in output
    assert "### 2. `beta.md`" in output
    assert payload["children"] == []
    assert [item["address"] for item in payload["linked_references"]] == [
        "alpha.md",
        "beta.md",
    ]
    assert "Children" not in rich
    assert "Linked References" in rich


def test_linked_child_reference_leaves_unlinked_children_visible(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "sase" / "memory" / "parent.md",
        _note("# Parent\nSee [[linked]].\n"),
    )
    _write(
        tmp_path / "sase" / "memory" / "linked.md",
        _note("# Linked\n", description="Linked child.").replace(
            "parent: AGENTS.md", "parent: parent.md"
        ),
    )
    _write(
        tmp_path / "sase" / "memory" / "unlinked.md",
        _note("# Unlinked\n", description="Unlinked child.").replace(
            "parent: AGENTS.md", "parent: parent.md"
        ),
    )

    batch = _resolve(tmp_path, ["parent.md"])
    output = memory_selector_batch_markdown(batch)
    payload = _json_payload(batch)
    rich = _rich_text(batch)

    children_section = output.split("## Children", maxsplit=1)[1].split(
        "## Linked References", maxsplit=1
    )[0]
    assert "sase/memory/unlinked.md" in children_section
    assert "sase/memory/linked.md" not in children_section
    assert payload["children"] == [
        {"path": "sase/memory/unlinked.md", "description": "Unlinked child."}
    ]
    assert payload["linked_references"] == [
        {
            "address": "linked.md",
            "always_loaded": False,
            "label": "Linked",
            "summary": "Linked child.",
        }
    ]
    assert "Children" in rich
    assert "sase/memory/unlinked.md" in rich
    assert "Linked References" in rich


def test_note_markdown_lists_unresolved_targets_last(tmp_path: Path) -> None:
    _seed_decisions_web(tmp_path)
    _write(
        tmp_path / "sase" / "memory" / "foo.md",
        _note("# Body\nSee [[decisions:single-turn-agents]] and [[does-not-exist]].\n"),
    )

    output = memory_selector_batch_markdown(_resolve(tmp_path, ["foo.md"]))

    assert "### 1. `decisions:single-turn-agents`" in output
    assert output.index("### 1. `decisions:single-turn-agents`") < output.index(
        "Unresolved: `does-not-exist`"
    )
