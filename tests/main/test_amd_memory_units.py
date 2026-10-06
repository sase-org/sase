"""Tests for the structured ``sase.amd.memory_units`` API."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.amd.init import plan_amd_memory_sync
from sase.amd.memory_units import (
    collect_memory_root_units,
    render_memory_root_units,
)
from sase.main.init_memory.models import LinkedRepoMemoryEntry
from tests.main.init_memory_handler_helpers import long_note, short_note, write


def _fixture_root(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    write(root / "sase.yml", "is_sase_managed: true\n")
    write(
        root / "sase" / "memory" / "gotchas.md",
        short_note("# Gotchas\n\n## Trap\n"),
    )
    write(
        root / "sase" / "memory" / "cli_rules.md",
        long_note("# CLI Rules\n", description="Rules for CLI work."),
    )
    write(
        root / "sase" / "memory" / "nodesc.md",
        long_note("# Nodesc\n\nFirst body paragraph here.\n", description=None),
    )
    write(
        root / "sase" / "memory" / "glossary.md",
        "---\nweb: true\nroster: list\nstrand_noun: term\ntype: reference\n"
        "parent: AGENTS.md\ndescription: Glossary web.\n---\n# Glossary\n",
    )
    write(
        root / "sase" / "memory" / "glossary" / "stitch.md",
        "---\nkeyword: Stitch\nsummary: A stitch links things.\n---\n# Stitch\n",
    )
    return root


def test_units_render_matches_legacy_plan_output(tmp_path: Path) -> None:
    """The units round-trip reproduces the legacy renderer byte-for-byte."""
    root = _fixture_root(tmp_path)
    plan = plan_amd_memory_sync(
        root,
        derive_project_title=True,
        generated_short_notes={},
        generated_long_notes={},
        generated_web_notes={},
    )
    assert not plan.blockers
    assert plan.title is not None
    assert plan.agents_content is not None

    units = collect_memory_root_units(
        root,
        plan.title,
        generated_short_notes={},
        generated_long_notes={},
        generated_web_notes={},
    )
    rendered, error = render_memory_root_units(units)
    assert error is None
    assert rendered == plan.agents_content


def test_units_render_matches_plan_with_descriptions(tmp_path: Path) -> None:
    """Passing the plan's own descriptions still renders identical bytes."""
    root = _fixture_root(tmp_path)
    plan = plan_amd_memory_sync(
        root,
        derive_project_title=True,
        generated_short_notes={},
        generated_long_notes={},
        generated_web_notes={},
    )
    assert not plan.blockers
    assert plan.title is not None

    from sase.amd._memory import _long_memory_descriptions

    descriptions = _long_memory_descriptions(
        root,
        {},
        source_memory_root=None,
        excluded_note_paths=frozenset(),
    )
    units = collect_memory_root_units(
        root,
        plan.title,
        generated_short_notes={},
        generated_long_notes={},
        generated_web_notes={},
        long_memory_descriptions=descriptions,
    )
    rendered, error = render_memory_root_units(units)
    assert error is None
    assert rendered == plan.agents_content


def test_units_identical_from_different_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit-root collection sees the same inputs from any cwd."""
    root = _fixture_root(tmp_path)
    first = collect_memory_root_units(root, "Title")
    monkeypatch.chdir(tmp_path)
    second = collect_memory_root_units(root, "Title")
    assert first == second


def test_reference_fallback_flag(tmp_path: Path) -> None:
    """The fallback flag marks only legacy ``AGENTS.md`` descriptions."""
    root = _fixture_root(tmp_path)
    write(
        root / "AGENTS.md",
        "# Previous\n\n**`sase/memory/nodesc.md`**\nLegacy description survives.\n",
    )
    units = collect_memory_root_units(root, "Title")
    by_path = {unit.relative_path: unit for unit in units.references}
    assert by_path["sase/memory/nodesc.md"].used_legacy_fallback is True
    assert by_path["sase/memory/nodesc.md"].description == (
        "Legacy description survives."
    )
    assert by_path["sase/memory/cli_rules.md"].used_legacy_fallback is False


def test_core_unit_fields_and_contract_flag(tmp_path: Path) -> None:
    """Core units carry stems, titles, sources, and the generated flag."""
    from sase.main.init_memory.root_rendering_notes import generated_short_notes

    root = _fixture_root(tmp_path)
    overlay = generated_short_notes(
        "# SASE = Structured Agentic Software Engineering (sase)\n"
    )
    units = collect_memory_root_units(root, "Title", generated_short_notes=overlay)
    by_path = {unit.relative_path: unit for unit in units.core}
    gotchas = by_path["sase/memory/gotchas.md"]
    assert gotchas.stem == "gotchas"
    assert gotchas.title == "Gotchas"
    assert gotchas.generated_contract is False
    assert gotchas.source_path == root / "sase" / "memory" / "gotchas.md"
    assert "## Trap" in gotchas.source_bytes
    assert gotchas.text.startswith("### Gotchas (gotchas)\n")

    contract = by_path["sase/memory/sase.md"]
    assert contract.generated_contract is True
    assert contract.title == "SASE = Structured Agentic Software Engineering (sase)"


def test_web_unit_block_and_strands(tmp_path: Path) -> None:
    """Web units carry the inlined block, descriptor source, and strands."""
    root = _fixture_root(tmp_path)
    units = collect_memory_root_units(root, "Title")
    assert len(units.webs) == 1
    web = units.webs[0]
    assert web.stem == "glossary"
    assert web.title == "Glossary"
    assert web.block.startswith("### Glossary (glossary)\n")
    assert web.descriptor_source == root / "sase" / "memory" / "glossary.md"
    assert web.strand_files == (root / "sase" / "memory" / "glossary" / "stitch.md",)


def test_reference_entry_text_has_no_positional_number(tmp_path: Path) -> None:
    """Per-entry renders omit the positional list number the legacy join adds."""
    root = _fixture_root(tmp_path)
    units = collect_memory_root_units(root, "Title")
    by_path = {unit.relative_path: unit for unit in units.references}
    entry = by_path["sase/memory/cli_rules.md"].entry_text
    assert entry.startswith("**`sase/memory/cli_rules.md`**")
    assert "Rules for CLI work." in entry


def test_contract_inputs_passthrough(tmp_path: Path) -> None:
    """Project name, linked entries, and template path land on the units."""
    root = _fixture_root(tmp_path)
    entries = (LinkedRepoMemoryEntry(name="sase-core", description="Core backend."),)
    template = root / "AGENTS.template.md"
    units = collect_memory_root_units(
        root,
        "Title",
        project_name="proj",
        linked_entries=entries,
        contract_template_path=template,
        linked_entries_source=root / "sase.yml",
    )
    assert units.contract_inputs.project_name == "proj"
    assert units.contract_inputs.linked_entries == entries
    assert units.contract_inputs.template_path == template
    assert units.contract_inputs.linked_entries_source == root / "sase.yml"
    assert units.intros.core
    assert units.intros.reference
    assert units.intros.webs


def test_minimal_golden_render(tmp_path: Path) -> None:
    """A one-note root renders the exact legacy document bytes."""
    root = tmp_path / "tiny"
    write(root / "sase.yml", "is_sase_managed: true\n")
    write(
        root / "sase" / "memory" / "gotchas.md",
        short_note("# Gotchas\n\n## Trap\n"),
    )
    units = collect_memory_root_units(root, "Test Instructions")
    rendered, error = render_memory_root_units(units)
    assert error is None
    assert rendered == (
        "# Test Instructions\n"
        "\n"
        "## 1. Core Memory\n"
        "\n"
        "The following memories contain core (always loaded) context:\n"
        "\n"
        "### 1.1 Gotchas (gotchas)\n"
        "\n"
        "#### 1.1.1 Trap\n"
        "\n"
        "## 2. Reference Memory\n"
        "\n"
        "\n"
        "\n"
        "\n"
    )
