"""Tests for inline-note rendering of memory selector batches."""

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


def test_note_markdown_renders_inline_child_without_children_listing(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "sase" / "memory" / "parent.md",
        _note("# Parent\n![[child]]\n"),
    )
    _write(
        tmp_path / "sase" / "memory" / "child.md",
        _note("# Child\n", description="A child note.").replace(
            "parent: AGENTS.md", "parent: parent.md"
        ),
    )

    output = memory_selector_batch_markdown(_resolve(tmp_path, ["parent.md"]))

    assert "# Parent" in output
    assert "# Child" in output
    assert "## Children" not in output
    assert "## Linked References" not in output


def test_inline_note_outputs_preserve_unread_grandchild_listing(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "sase" / "memory" / "root.md",
        _note("# Root\n![[child]]\n"),
    )
    _write(
        tmp_path / "sase" / "memory" / "child.md",
        _note("# Child\nCHILD_BODY\n", description="Child note.").replace(
            "parent: AGENTS.md", "parent: root.md"
        ),
    )
    _write(
        tmp_path / "sase" / "memory" / "grandchild.md",
        _note(
            "# Grandchild\nGRANDCHILD_BODY\n",
            description="GRANDCHILD_DESCRIPTION",
        ).replace("parent: AGENTS.md", "parent: child.md"),
    )

    batch = _resolve(tmp_path, ["root.md"])
    output = memory_selector_batch_markdown(batch)
    payload = _json_payload(batch)
    rich = _rich_text(batch)

    assert "CHILD_BODY" in output
    assert "grandchild.md" in output
    assert "GRANDCHILD_DESCRIPTION" in output
    assert "GRANDCHILD_BODY" not in output
    assert "grandchild.md" in rich
    assert "GRANDCHILD_DESCRIPTION" in rich
    assert "GRANDCHILD_BODY" not in rich
    (child_payload,) = payload["note"]["inline_notes"]
    assert child_payload["children"] == [
        {
            "path": "sase/memory/grandchild.md",
            "description": "GRANDCHILD_DESCRIPTION",
        }
    ]
    assert child_payload["inline_notes"] == []
    assert "GRANDCHILD_BODY" not in json.dumps(payload)


def test_batch_json_suppresses_rendered_nested_inline_child_rows(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "sase" / "memory" / "root.md",
        _note("# Root\n![[child]]\n"),
    )
    _write(
        tmp_path / "sase" / "memory" / "child.md",
        _note("# Child\n![[grandchild]]\n", description="Child note.").replace(
            "parent: AGENTS.md", "parent: root.md"
        ),
    )
    _write(
        tmp_path / "sase" / "memory" / "grandchild.md",
        _note(
            "# Grandchild\nGRANDCHILD_BODY\n",
            description="GRANDCHILD_DESCRIPTION",
        ).replace("parent: AGENTS.md", "parent: child.md"),
    )
    _write(tmp_path / "sase" / "memory" / "other.md", _note("# Other\n"))

    batch = _resolve(tmp_path, ["root.md", "other.md"])
    output = memory_selector_batch_markdown(batch)
    payload = _json_payload(batch)
    rich = _rich_text(batch)

    assert output.count("GRANDCHILD_BODY") == 1
    assert rich.count("GRANDCHILD_BODY") == 1
    assert "GRANDCHILD_DESCRIPTION" not in output
    root_payload = payload["notes"][0]
    (child_payload,) = root_payload["inline_notes"]
    (grandchild_payload,) = child_payload["inline_notes"]
    assert grandchild_payload["canonical_path"] == "grandchild.md"
    assert child_payload["children"] == []


def test_batch_json_filters_nested_references_to_batch_rendered_notes(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "sase" / "memory" / "root.md",
        _note("# Root\n![[child]]\n"),
    )
    _write(
        tmp_path / "sase" / "memory" / "child.md",
        _note("# Child\nSee [[grandchild]].\n", description="Child note.").replace(
            "parent: AGENTS.md", "parent: root.md"
        ),
    )
    _write(
        tmp_path / "sase" / "memory" / "grandchild.md",
        _note("# Grandchild\nGRANDCHILD_BODY\n").replace(
            "parent: AGENTS.md", "parent: child.md"
        ),
    )

    batch = _resolve(tmp_path, ["root.md", "grandchild.md"])
    payload = _json_payload(batch)

    root_payload = payload["notes"][0]
    assert root_payload["linked_references"] == []
    (child_payload,) = root_payload["inline_notes"]
    assert child_payload["linked_references"] == []
    assert [note["canonical_path"] for note in payload["notes"]] == [
        "root.md",
        "grandchild.md",
    ]


def test_depth_limited_inline_note_json_lists_truncated_leaf_on_nested_note(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "sase" / "memory" / "alpha.md",
        _note("# Alpha\n![[beta]]\n"),
    )
    _write(
        tmp_path / "sase" / "memory" / "beta.md",
        _note("# Beta\n![[gamma]]\n"),
    )
    _write(tmp_path / "sase" / "memory" / "gamma.md", _note("# Gamma\n"))

    batch = _resolve(tmp_path, ["alpha.md"], depth=1)
    output = memory_selector_batch_markdown(batch)
    payload = _json_payload(batch)

    assert "# Beta" in output
    assert "# Gamma" not in output
    assert "### 1. `gamma.md`" in output
    (beta_payload,) = payload["note"]["inline_notes"]
    assert beta_payload["inline_notes"] == []
    assert beta_payload["linked_references"] == [
        {
            "address": "gamma.md",
            "always_loaded": False,
            "label": "Gamma",
            "summary": "A note.",
        }
    ]


def test_multi_root_shared_inline_note_body_renders_once(tmp_path: Path) -> None:
    _write(
        tmp_path / "sase" / "memory" / "shared.md",
        _note("# Shared\nSHARED_BODY\n"),
    )
    _write(tmp_path / "sase" / "memory" / "alpha.md", _note("# Alpha\n![[shared]]\n"))
    _write(tmp_path / "sase" / "memory" / "beta.md", _note("# Beta\n![[shared]]\n"))

    batch = _resolve(tmp_path, ["alpha.md", "beta.md"])
    output = memory_selector_batch_markdown(batch)
    payload = _json_payload(batch)
    rich = _rich_text(batch)

    assert output.count("SHARED_BODY") == 1
    assert rich.count("SHARED_BODY") == 1
    assert [note["canonical_path"] for note in payload["notes"]] == [
        "alpha.md",
        "beta.md",
    ]
    assert payload["notes"][0]["inline_notes"][0]["canonical_path"] == "shared.md"
    assert payload["notes"][1]["inline_notes"] == []
    assert all(note["linked_references"] == [] for note in payload["notes"])


def test_reference_before_inline_suppresses_reference_and_child_listing(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "sase" / "memory" / "parent.md",
        _note("# Parent\nSee [[child]] before ![[child]].\n"),
    )
    _write(
        tmp_path / "sase" / "memory" / "child.md",
        _note("# Child\nCHILD_BODY\n", description="A child note.").replace(
            "parent: AGENTS.md", "parent: parent.md"
        ),
    )

    batch = _resolve(tmp_path, ["parent.md"])
    output = memory_selector_batch_markdown(batch)
    payload = _json_payload(batch)
    rich = _rich_text(batch)

    assert "CHILD_BODY" in output
    assert "## Children" not in output
    assert "## Linked References" not in output
    assert payload["children"] == []
    assert payload["linked_references"] == []
    assert payload["note"]["inline_notes"][0]["canonical_path"] == "child.md"
    assert "Children" not in rich
    assert "Linked References" not in rich


def test_depth_zero_lists_flat_note_inline_link_as_a_reference(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "sase" / "memory" / "child.md", _note("# Child\n"))
    _write(
        tmp_path / "sase" / "memory" / "parent.md",
        _note("# Parent\n![[child]]\n"),
    )

    output = memory_selector_batch_markdown(_resolve(tmp_path, ["parent.md"], depth=0))

    assert "# Child" not in output
    assert "### 1. `child.md`" in output
    assert "**Child**" in output


def test_truncated_flat_note_inline_chain_lists_leaf_as_reference(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "sase" / "memory" / "alpha.md",
        _note("# Alpha\n![[beta]]\n"),
    )
    _write(
        tmp_path / "sase" / "memory" / "beta.md",
        _note("# Beta\n![[gamma]]\n"),
    )
    _write(tmp_path / "sase" / "memory" / "gamma.md", _note("# Gamma\n"))

    output = memory_selector_batch_markdown(_resolve(tmp_path, ["alpha.md"], depth=1))

    assert "# Beta" in output
    assert "# Gamma" not in output
    assert "### 1. `gamma.md`" in output


def test_note_markdown_omits_section_when_there_are_no_reference_links(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "sase" / "memory" / "foo.md", _note("# Foo body\n"))

    assert "Linked References" not in memory_selector_batch_markdown(
        _resolve(tmp_path, ["foo.md"])
    )
