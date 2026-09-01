"""Tests for Markdown, JSON, and rich rendering of memory selector batches."""

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
    parent_header = "---------- MEMORY FILE: parent.md"
    child_header = "---------- MEMORY FILE: child.md"
    assert output.startswith(f"\n{parent_header}\n\n")
    parent_header_at = output.index(parent_header)
    children_section = output.index("## Children")
    child_entry = output.index("`sase/memory/child.md`", children_section)
    child_header_at = output.index(child_header)
    assert parent_header_at < children_section < child_entry < child_header_at


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


def test_note_markdown_omits_section_when_there_are_no_reference_links(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "sase" / "memory" / "foo.md", _note("# Foo body\n"))

    assert "Linked References" not in memory_selector_batch_markdown(
        _resolve(tmp_path, ["foo.md"])
    )


def test_inline_strand_renders_at_the_bottom_without_a_listing(
    tmp_path: Path,
) -> None:
    _seed_decisions_web(tmp_path)

    output = memory_selector_batch_markdown(
        _resolve(tmp_path, ["decisions:gates-never-block"])
    )

    assert "# A Gate Never Blocks" in output
    assert "# Agents Are Single-Turn" in output
    assert output.index("A Gate Never Blocks") < output.index("Agents Are Single-Turn")
    assert "Linked References" not in output


def test_web_section_lists_reference_links_and_skips_inline_targets(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "sase" / "memory" / "decisions.md",
        "---\nweb: true\ndescription: Decision records.\nroster: list\n---\n\nPreamble.\n",
    )
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

    output = memory_selector_batch_markdown(_resolve(tmp_path, ["decisions:alpha"]))

    assert "# Alpha" in output
    assert "# Beta" in output
    assert "# Gamma" not in output
    assert "### 1. `decisions:gamma`" in output
    assert "**Gamma** — Gamma." in output
    assert "decisions:beta" not in output.split("## Linked References")[-1]


def test_web_section_dedupes_reference_links_across_rendered_nodes(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "sase" / "memory" / "decisions.md",
        "---\nweb: true\ndescription: Decision records.\nroster: list\n---\n\nPreamble.\n",
    )
    _write(
        tmp_path / "sase" / "memory" / "decisions" / "alpha.md",
        "---\nkeyword: Alpha\nsummary: Alpha.\n---\nSee [[decisions/gamma]].\n",
    )
    _write(
        tmp_path / "sase" / "memory" / "decisions" / "beta.md",
        "---\nkeyword: Beta\nsummary: Beta.\n---\nAlso [[decisions/gamma]].\n",
    )
    _write(
        tmp_path / "sase" / "memory" / "decisions" / "gamma.md",
        "---\nkeyword: Gamma\nsummary: Gamma.\n---\nLeaf.\n",
    )

    output = memory_selector_batch_markdown(
        _resolve(tmp_path, ["decisions:alpha", "decisions:beta"])
    )

    assert output.count("### 1. `decisions:gamma`") == 1
    assert "### 2." not in output


def test_web_section_omits_links_to_strands_it_already_renders(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "sase" / "memory" / "decisions.md",
        "---\nweb: true\ndescription: Decision records.\nroster: list\n---\n\nPreamble.\n",
    )
    _write(
        tmp_path / "sase" / "memory" / "decisions" / "alpha.md",
        "---\nkeyword: Alpha\nsummary: Alpha.\n---\nSee ![[decisions/beta]].\n",
    )
    _write(
        tmp_path / "sase" / "memory" / "decisions" / "beta.md",
        "---\nkeyword: Beta\nsummary: Beta.\n---\nBack to [[decisions/alpha]].\n",
    )

    output = memory_selector_batch_markdown(_resolve(tmp_path, ["decisions:alpha"]))

    assert "# Beta" in output
    assert "## Linked References" not in output


def test_depth_zero_lists_inline_link_as_a_reference(tmp_path: Path) -> None:
    _seed_decisions_web(tmp_path)

    output = memory_selector_batch_markdown(
        _resolve(tmp_path, ["decisions:gates-never-block"], depth=0)
    )

    assert "# Agents Are Single-Turn" not in output
    assert "### 1. `decisions:single-turn-agents`" in output


def test_truncated_inline_link_is_listed_as_a_reference(tmp_path: Path) -> None:
    _write(
        tmp_path / "sase" / "memory" / "decisions.md",
        "---\nweb: true\ndescription: Decision records.\nroster: list\n---\n\nPreamble.\n",
    )
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

    output = memory_selector_batch_markdown(
        _resolve(tmp_path, ["decisions:alpha"], depth=1)
    )

    assert "# Gamma" not in output
    assert "### 1. `decisions:gamma`" in output


def test_core_note_and_web_descriptor_carry_always_loaded_marker(
    tmp_path: Path,
) -> None:
    _seed_glossary_web(tmp_path)
    _write(
        tmp_path / "sase" / "memory" / "core.md",
        "---\ntype: core\nparent: AGENTS.md\ndescription: Always loaded.\n---\n# Core\n",
    )
    _write(
        tmp_path / "sase" / "memory" / "foo.md",
        _note("# Body\nSee [[core.md]] and [[glossary]].\n"),
    )

    output = memory_selector_batch_markdown(_resolve(tmp_path, ["foo.md"]))

    assert "always-loaded core memory — already in your context" in output
    assert "### 1. `core.md`" in output
    assert "### 2. `glossary`" in output


def test_note_json_payload_includes_links_and_linked_references(
    tmp_path: Path,
) -> None:
    _seed_decisions_web(tmp_path)
    _write(
        tmp_path / "sase" / "memory" / "foo.md",
        _note("# Body\nSee [[decisions:single-turn-agents]] and [[missing]].\n"),
    )

    payload = _json_payload(_resolve(tmp_path, ["foo.md"]))

    assert payload["linked_references"] == [
        {
            "address": "decisions:single-turn-agents",
            "always_loaded": False,
            "label": "Agents Are Single-Turn",
            "summary": "Turn summary.",
        }
    ]
    assert payload["note"]["links"] == [
        {
            "address": "decisions:single-turn-agents",
            "kind": "reference",
            "label": "Agents Are Single-Turn",
            "resolved": True,
            "summary": "Turn summary.",
            "target": "decisions:single-turn-agents",
        },
        {
            "address": None,
            "kind": "reference",
            "label": None,
            "resolved": False,
            "summary": None,
            "target": "missing",
        },
    ]


def test_web_json_payload_includes_section_listings_and_node_links(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "sase" / "memory" / "decisions.md",
        "---\nweb: true\ndescription: Decision records.\nroster: list\n---\n\nPreamble.\n",
    )
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

    payload = _json_payload(_resolve(tmp_path, ["decisions:alpha"]))

    (web,) = payload["webs"]
    assert web["linked_references"] == [
        {
            "address": "decisions:gamma",
            "always_loaded": False,
            "label": "Gamma",
            "summary": "Gamma.",
        }
    ]
    alpha = next(node for node in web["nodes"] if node["slug"] == "alpha")
    kinds = {item["address"]: item["kind"] for item in alpha["links"]}
    assert kinds == {"decisions:beta": "inline", "decisions:gamma": "reference"}
    beta = next(node for node in web["nodes"] if node["slug"] == "beta")
    assert beta["links"] == []


def test_rich_note_and_web_render_linked_references_block(tmp_path: Path) -> None:
    _seed_decisions_web(tmp_path)
    _write(
        tmp_path / "sase" / "memory" / "foo.md",
        _note("# Body\nSee [[decisions:single-turn-agents]].\n"),
    )

    note_text = _rich_text(_resolve(tmp_path, ["foo.md"]))
    assert "Linked References" in note_text
    assert "decisions:single-turn-agents" in note_text
    assert "Agents Are Single-Turn" in note_text

    _write(
        tmp_path / "sase" / "memory" / "decisions" / "alpha.md",
        "---\nkeyword: Alpha\nsummary: Alpha.\n---\nSee [[decisions/single-turn-agents]].\n",
    )
    web_text = _rich_text(_resolve(tmp_path, ["decisions:alpha"]))
    assert "Linked References" in web_text
    assert "decisions:single-turn-agents" in web_text


def _seed_superseded_decision(root: Path) -> None:
    _seed_decisions_web(root)
    _write(
        root / "sase" / "memory" / "decisions" / "memory-webs.md",
        "---\n"
        "keyword: Memory Webs\n"
        "summary: Flat descriptor plus strands.\n"
        "metadata:\n"
        "  status: superseded-in-part\n"
        "  superseded_by:\n"
        "    - decisions/gates-never-block\n"
        "    - decisions/single-turn-agents\n"
        "---\n"
        "Claim body. See [[decisions/gates-never-block]] and "
        "[[decisions/single-turn-agents]].\n",
    )


def test_web_markdown_emits_supersession_line_after_provenance(
    tmp_path: Path,
) -> None:
    _seed_superseded_decision(tmp_path)

    markdown = memory_selector_batch_markdown(
        _resolve(tmp_path, ["decisions:memory-webs"], depth=0)
    )

    assert "*Requested · project*" in markdown
    assert (
        "> **Partly superseded** by `decisions/gates-never-block`, "
        "`decisions/single-turn-agents`."
    ) in markdown
    provenance_at = markdown.index("*Requested · project*")
    marker_at = markdown.index("> **Partly superseded**")
    body_at = markdown.index("Claim body.")
    assert provenance_at < marker_at < body_at


def test_web_json_includes_supersession_payload_or_null(tmp_path: Path) -> None:
    _seed_superseded_decision(tmp_path)

    payload = _json_payload(_resolve(tmp_path, ["decisions"], depth=0))
    (web,) = payload["webs"]
    by_slug = {node["slug"]: node for node in web["nodes"]}

    assert by_slug["memory-webs"]["supersession"] == {
        "status": "superseded-in-part",
        "partial": True,
        "superseded_by": [
            "decisions/gates-never-block",
            "decisions/single-turn-agents",
        ],
    }
    assert by_slug["gates-never-block"]["supersession"] is None
    assert by_slug["single-turn-agents"]["supersession"] is None


def test_web_rich_emits_supersession_sentence(tmp_path: Path) -> None:
    _seed_superseded_decision(tmp_path)

    text = _rich_text(_resolve(tmp_path, ["decisions:memory-webs"], depth=0))

    assert (
        "Partly superseded by `decisions/gates-never-block`, "
        "`decisions/single-turn-agents`."
    ) in text
    assert "Superseded by" not in text.replace("Partly superseded by", "")
