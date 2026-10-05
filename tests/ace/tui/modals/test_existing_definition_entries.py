"""Pure catalog conversion, ordering, and verdict copy for the finder."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.modals.existing_definition_entries import (
    ExistingDefinitionEntry,
    existing_entry_verdict,
    macro_existing_entries,
    rank_existing_entries,
    snippet_existing_entries,
)
from sase.ace.tui.modals.mini_macro_target_catalog import (
    MiniMacroDefinition,
    MiniMacroTargetCatalog,
)
from sase.ace.tui.modals import mini_macro_target_catalog as catalog_mod
from sase.ace.tui.modals.mini_macro_target_catalog import load_mini_macro_target_catalog
from sase.ace.tui.modals.macro_location_modal import MacroLocation
from sase.ace.tui.modals.unified_macro_save_modal import UnifiedSaveLocation
from sase.legacy_xprompt_names import LEGACY_XPROMPT_SOURCE_KIND
from sase.macro.models import Macro
from sase.snippet.redefinition import SnippetDefinitionSite


def _macro(
    name: str,
    *,
    path: str,
    compatibility: str = "editable",
    effective: bool = True,
    precedence: int = 0,
    kind: str = "macro",
    shadowed_by: str | None = None,
    shadows: str | None = None,
) -> MiniMacroDefinition:
    return MiniMacroDefinition(
        name=name,
        workflow_kind=kind,  # type: ignore[arg-type]
        source_path=path,
        display_path=path,
        storage_format=None,
        entry_name=None,
        location_path=path,
        precedence=precedence,
        compatibility=compatibility,  # type: ignore[arg-type]
        origin_label="built-in" if compatibility == "read_only" else None,
        incompatible_reason=(
            "macro swarms cannot be opened" if compatibility == "incompatible" else None
        ),
        effective=effective,
        shadowed_by=shadowed_by,
        shadows=shadows,
    )


def _entry(
    entry_id: str,
    name: str,
    *,
    status: str = "active",
    path: str | None = None,
    precedence: int = 0,
) -> ExistingDefinitionEntry:
    return ExistingDefinitionEntry(
        entry_id=entry_id,
        kind="macro",
        name=name,
        reference=f"#{name}",
        display_path=path or f"/macros/{name}.md",
        origin_label="built-in" if status == "read_only" else None,
        status=status,  # type: ignore[arg-type]
        shadowed_by="/winner.md" if status == "shadowed" else None,
        shadows=None,
        reason="macro swarms cannot be opened" if status == "incompatible" else None,
        precedence=precedence,
    )


def test_macro_entries_build_physical_ids_status_and_reasons() -> None:
    definitions = (
        _macro("review", path="/project/review.md", shadows="/home/review.md"),
        _macro(
            "review",
            path="/home/review.md",
            effective=False,
            precedence=2,
            shadowed_by="/project/review.md",
        ),
        _macro("locked", path="/pkg/locked.md", compatibility="read_only"),
        _macro("swarm", path="/project/swarm.md", compatibility="incompatible"),
        _macro(
            "flow", path="/pkg/flow.yml", compatibility="incompatible", kind="workflow"
        ),
    )
    catalog = MiniMacroTargetCatalog(definitions=definitions, destinations=())

    entries = macro_existing_entries(catalog)

    assert [entry.status for entry in entries] == [
        "active",
        "shadowed",
        "read_only",
        "incompatible",
        "incompatible",
    ]
    assert entries[0].entry_id == "macro:/project/review.md::review"
    assert entries[0].shadows == "/home/review.md"
    assert entries[1].shadowed_by == "/project/review.md"
    assert entries[2].chip == "built-in"
    assert entries[3].chip == "swarm"
    assert entries[4].chip == "workflow"
    assert entries[3].reason == "macro swarms cannot be opened"


def test_snippet_entries_preserve_source_origin_and_templates() -> None:
    sites = (
        SnippetDefinitionSite(
            trigger="todo",
            kind="user",
            path="/home/sase.yml",
            display="~/.config/sase/sase.yml",
            template="user body",
            writable=True,
            active=False,
            shadowed_by="./sase/sase.yml",
            layer="user",
        ),
        SnippetDefinitionSite(
            trigger="todo",
            kind="project",
            path="/project/sase.yml",
            display="./sase/sase.yml",
            template="project body",
            writable=True,
            active=True,
            shadowed_by=None,
            layer="project",
        ),
        SnippetDefinitionSite(
            trigger="tab",
            kind="plugin",
            path="/plugins/help/sase.yml",
            display="plugin sase_help",
            template="plugin template",
            writable=False,
            active=True,
            shadowed_by=None,
            layer="plugin:sase_help",
        ),
        SnippetDefinitionSite(
            trigger="macro",
            kind=LEGACY_XPROMPT_SOURCE_KIND,
            path=None,
            display="#review (macro snippet)",
            template="from macro",
            writable=False,
            active=True,
            shadowed_by=None,
            macro_name="review",
        ),
        SnippetDefinitionSite(
            trigger="legacy-macro",
            kind="macro",
            path=None,
            display="#legacy (macro snippet)",
            template="legacy macro body",
            writable=False,
            active=True,
            shadowed_by=None,
            macro_name="legacy",
        ),
    )

    entries = snippet_existing_entries(sites)

    assert [entry.status for entry in entries] == [
        "shadowed",
        "active",
        "read_only",
        "read_only",
        "read_only",
    ]
    assert entries[0].entry_id == "snippet:user:/home/sase.yml:todo"
    assert entries[0].preview_text == "user body"
    assert entries[1].shadows == "~/.config/sase/sase.yml"
    assert entries[2].origin_label == "plugin sase_help"
    assert entries[2].chip == "plugin"
    assert entries[3].origin_label == "from #review"
    assert entries[3].chip == "from #macro"
    assert entries[4].origin_label == "from #legacy"
    assert entries[4].chip == "from #macro"


def test_config_loader_source_id_produces_one_active_finder_entry(
    tmp_path: Path, monkeypatch
) -> None:
    config = tmp_path / "sase.yml"
    config.write_text("macros:\n  review:\n    content: body\n", encoding="utf-8")
    row = UnifiedSaveLocation(
        location=MacroLocation("User config", str(config), "config"),
        group="User config",
        display_path=str(config),
        names=frozenset({"review"}),
        precedence=0,
    )
    monkeypatch.setattr(
        catalog_mod,
        "get_all_macros",
        lambda project=None: {
            "review": Macro(name="review", content="body", source_path="config")
        },
    )
    monkeypatch.setattr(catalog_mod, "get_all_workflows", lambda project=None: {})
    monkeypatch.setattr(catalog_mod, "definition_file_for_source", lambda _: config)

    entries = macro_existing_entries(load_mini_macro_target_catalog(locations=[row]))

    assert len(entries) == 1
    assert entries[0].status == "active"
    assert entries[0].display_path == f"{config}:review"


def test_empty_query_sorts_compatible_then_name_and_active_before_shadowed() -> None:
    entries = (
        _entry("readonly", "aardvark", status="read_only"),
        _entry("shadowed", "alpha", status="shadowed", precedence=1),
        _entry("active", "alpha", precedence=4),
        _entry("beta", "beta"),
        _entry("bad", "bad", status="incompatible"),
    )

    ranked = rank_existing_entries(entries, "")

    assert [row.entry.entry_id for row in ranked] == [
        "readonly",
        "active",
        "shadowed",
        "beta",
        "bad",
    ]


def test_query_ranks_name_matches_before_path_only_matches_and_returns_runs() -> None:
    entries = (
        _entry("path", "other", path="/docs/review-guide.md"),
        _entry("exact", "review"),
        _entry("prefix", "reviewer"),
    )

    ranked = rank_existing_entries(entries, "review")

    assert [row.entry.entry_id for row in ranked] == ["exact", "prefix", "path"]
    assert ranked[0].name_match is not None
    assert ranked[0].name_match.runs
    assert ranked[2].name_match is None
    assert ranked[2].path_match is not None
    assert ranked[2].path_match.runs


def test_entry_verdict_copy_covers_all_statuses() -> None:
    active = _entry("active", "review")
    shadowed = _entry("shadowed", "review", status="shadowed")
    readonly = _entry("readonly", "review", status="read_only")
    incompatible = _entry("bad", "swarm", status="incompatible")

    assert existing_entry_verdict(active) == (
        "success",
        "✓ Edit #review in place · /macros/review.md",
    )
    assert existing_entry_verdict(shadowed) == (
        "warning",
        "⚠ #review in /macros/review.md is shadowed by /winner.md — edits here won't take effect",
    )
    assert existing_entry_verdict(readonly) == (
        "warning",
        "⚠ #review is built-in (read-only) — Enter picks where your override should live",
    )
    assert existing_entry_verdict(incompatible) == (
        "error",
        "✗ Cannot open #swarm: macro swarms cannot be opened",
    )
