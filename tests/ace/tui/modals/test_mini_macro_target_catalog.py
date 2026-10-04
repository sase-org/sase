"""Mini-macro target catalog behavior."""

from __future__ import annotations

from pathlib import Path

import yaml

from sase.ace.tui.modals import mini_macro_target_catalog as catalog_mod
from sase.ace.tui.modals.mini_macro_target_catalog import (
    destination_target_for_name,
    load_mini_macro_target_catalog,
    mini_macro_prefix_matches,
    rebase_name_for_destination,
    validate_name_for_destination,
)
from sase.ace.tui.modals.unified_macro_save_modal import UnifiedSaveLocation
from sase.ace.tui.modals.macro_location_modal import MacroLocation
from sase.macro.models import Macro
from sase.macro.save import SaveTargetFormat
from sase.macro.write_targets import MacroWriteTarget


def _row(
    path: Path,
    *,
    names: frozenset[str] = frozenset(),
    location_type: str = "directory",
    label: str = "Test",
    group: str = "Project",
    precedence: int = 0,
    disabled_reason: str | None = None,
    namespace: str | None = None,
    builtin: bool = False,
) -> UnifiedSaveLocation:
    return UnifiedSaveLocation(
        location=MacroLocation(label, str(path), location_type),  # type: ignore[arg-type]
        group=group,
        display_path=str(path),
        names=names,
        precedence=precedence,
        disabled_reason=disabled_reason,
        namespace=namespace,
        builtin=builtin,
    )


def _write_macro(path: Path, body: str, *, name: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if name is None:
        path.write_text(body, encoding="utf-8")
        return
    path.write_text(f"---\nname: {name}\n---\n\n{body}\n", encoding="utf-8")


def _write_config(path: Path, entries: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"macros": entries}), encoding="utf-8")


def _empty_catalog_only(monkeypatch) -> None:
    monkeypatch.setattr(catalog_mod, "get_all_macros", lambda project=None: {})
    monkeypatch.setattr(catalog_mod, "get_all_workflows", lambda project=None: {})


def test_namespace_and_storage_mapping_for_directory_and_config_targets(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "macros"
    config = tmp_path / "sase.yml"
    dir_row = _row(directory, namespace="sase")
    config_row = _row(config, location_type="config", namespace="sase")

    dir_target = destination_target_for_name(
        dir_row,
        "sase/review",
        destinations=[dir_row, config_row],
    )
    assert dir_target.storage_name == "review"
    assert dir_target.path == str(directory / "review.md")
    assert validate_name_for_destination("review", dir_row) == (
        "Names saved here must start with sase/"
    )

    target = destination_target_for_name(
        config_row,
        "sase/review",
        destinations=[dir_row, config_row],
    )
    assert target.path == str(config)
    assert target.target_format is SaveTargetFormat.CONFIG
    assert target.entry_name == "review"


def test_catalog_indexes_directory_config_duplicates_and_swarm_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _empty_catalog_only(monkeypatch)
    high = tmp_path / "high"
    low = tmp_path / "low"
    config = tmp_path / "sase.yml"
    _write_macro(high / "review.md", "high")
    _write_macro(low / "review.md", "one\n---\ntwo")
    _write_config(config, {"review": {"content": "config"}})

    rows = [
        _row(high, names=frozenset({"review"}), precedence=0),
        _row(low, names=frozenset({"review"}), precedence=10),
        _row(
            config,
            names=frozenset({"review"}),
            location_type="config",
            group="Config files",
            precedence=20,
        ),
    ]
    catalog = load_mini_macro_target_catalog(locations=rows)

    definitions = catalog.definitions_for_name("review")
    assert [definition.display_path for definition in definitions]
    assert definitions[0].effective is True
    assert definitions[0].compatibility == "editable"
    assert definitions[0].shadows == str(low / "review.md")
    assert definitions[1].compatibility == "incompatible"
    assert "swarms" in (definitions[1].incompatible_reason or "")
    assert definitions[2].storage_format is SaveTargetFormat.CONFIG
    assert definitions[2].entry_name == "review"


def test_rebase_name_for_destination_seeds_and_strips_namespace(
    tmp_path: Path,
) -> None:
    project_row = _row(tmp_path / "project", namespace="sase")
    home_row = _row(tmp_path / "home")
    other_row = _row(tmp_path / "other", namespace="work")

    assert rebase_name_for_destination("review", project_row) == "sase/review"
    assert rebase_name_for_destination("sase/review", project_row) == "sase/review"
    assert rebase_name_for_destination("", project_row) == ""
    assert rebase_name_for_destination("review", home_row) == "review"
    assert (
        rebase_name_for_destination(
            "sase/review", home_row, from_destination=project_row
        )
        == "review"
    )
    assert (
        rebase_name_for_destination(
            "sase/review", other_row, from_destination=project_row
        )
        == "work/review"
    )
    assert (
        rebase_name_for_destination("review", other_row, from_destination=project_row)
        == "work/review"
    )


def test_catalog_only_workflows_skills_and_memory_are_incompatible(
    tmp_path: Path,
    monkeypatch,
) -> None:
    row = _row(tmp_path / "macros")
    monkeypatch.setattr(
        catalog_mod,
        "get_all_macros",
        lambda project=None: {
            "skill/review": Macro(
                name="skill/review",
                content="skill",
                source_path="skills/review.md",
                skill_name="review",
            ),
            "memory/obsidian": Macro(
                name="memory/obsidian",
                content="memory",
                source_path="memory/obsidian.md",
                memory_type="reference",
            ),
        },
    )
    monkeypatch.setattr(
        catalog_mod,
        "get_all_workflows",
        lambda project=None: {},
    )

    catalog = load_mini_macro_target_catalog(locations=[row])

    assert catalog.effective_definition("skill/review").workflow_kind == "skill"  # type: ignore[union-attr]
    assert catalog.effective_definition("skill/review").compatibility == "incompatible"  # type: ignore[union-attr]
    assert catalog.effective_definition("memory/obsidian").workflow_kind == "memory"  # type: ignore[union-attr]


def test_catalog_includes_read_only_plain_macros_and_rejects_swarms(
    tmp_path: Path,
    monkeypatch,
) -> None:
    row = _row(tmp_path / "macros")
    monkeypatch.setattr(
        catalog_mod,
        "get_all_macros",
        lambda project=None: {
            "legacy": Macro(
                name="legacy",
                content="legacy body",
                source_path=str(tmp_path / "legacy" / "legacy.md"),
                discovery_rank=0,
            ),
            "swarm": Macro(
                name="swarm",
                content="one\n---\ntwo",
                source_path=str(tmp_path / "legacy" / "swarm.md"),
            ),
        },
    )
    monkeypatch.setattr(catalog_mod, "get_all_workflows", lambda project=None: {})

    catalog = load_mini_macro_target_catalog(locations=[row])

    legacy = catalog.effective_definition("legacy")
    assert legacy is not None
    assert legacy.compatibility == "read_only"
    assert legacy.origin_label == "read-only"
    assert legacy.precedence > row.precedence
    swarm = catalog.effective_definition("swarm")
    assert swarm is not None
    assert swarm.compatibility == "incompatible"
    assert "swarms" in (swarm.incompatible_reason or "")


def test_catalog_deduplicates_deployed_and_chezmoi_source_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    deployed = tmp_path / "home" / "sase" / "macros" / "review.md"
    chezmoi_source = (
        tmp_path / "chezmoi" / "dot_config" / "sase" / "macros" / "review.md"
    )
    _write_macro(chezmoi_source, "review body")

    def resolve(path: Path | str) -> MacroWriteTarget:
        read_path = Path(path)
        write_path = chezmoi_source if read_path == deployed else read_path
        return MacroWriteTarget(
            read_path=read_path,
            write_path=write_path,
            apply_target=None,
            via_chezmoi=write_path != read_path,
        )

    monkeypatch.setattr(catalog_mod, "resolve_macro_write_target", resolve)
    monkeypatch.setattr(
        catalog_mod,
        "get_all_macros",
        lambda project=None: {
            "review": Macro(
                name="review",
                content="review body",
                source_path=str(deployed),
            )
        },
    )
    monkeypatch.setattr(catalog_mod, "get_all_workflows", lambda project=None: {})

    catalog = load_mini_macro_target_catalog(locations=[_row(chezmoi_source)])

    assert len(catalog.definitions_for_name("review")) == 1


def test_runtime_loader_source_overrides_row_precedence_for_effective_definition(
    tmp_path: Path,
    monkeypatch,
) -> None:
    higher_row_path = tmp_path / "row-first"
    active_path = tmp_path / "runtime-active"
    _write_macro(higher_row_path / "review.md", "row-first")
    _write_macro(active_path / "review.md", "runtime active")
    monkeypatch.setattr(
        catalog_mod,
        "get_all_macros",
        lambda project=None: {
            "review": Macro(
                name="review",
                content="runtime active",
                source_path=str(active_path / "review.md"),
            )
        },
    )
    monkeypatch.setattr(catalog_mod, "get_all_workflows", lambda project=None: {})

    catalog = load_mini_macro_target_catalog(
        locations=[
            _row(higher_row_path, names=frozenset({"review"}), precedence=0),
            _row(active_path, names=frozenset({"review"}), precedence=10),
        ]
    )

    definitions = catalog.definitions_for_name("review")
    assert definitions[0].source_path == str(active_path / "review.md")
    assert definitions[0].effective is True
    assert definitions[1].effective is False
    assert definitions[1].shadowed_by == str(active_path / "review.md")


def test_catalog_only_runtime_winner_orders_before_rows_but_keeps_late_rank(
    tmp_path: Path,
    monkeypatch,
) -> None:
    row_path = tmp_path / "row"
    catalog_path = tmp_path / "catalog-only" / "review.md"
    _write_macro(row_path / "review.md", "row body")
    monkeypatch.setattr(
        catalog_mod,
        "get_all_macros",
        lambda project=None: {
            "review": Macro(
                name="review",
                content="runtime body",
                source_path=str(catalog_path),
                discovery_rank=0,
            )
        },
    )
    monkeypatch.setattr(catalog_mod, "get_all_workflows", lambda project=None: {})

    catalog = load_mini_macro_target_catalog(
        locations=[_row(row_path, names=frozenset({"review"}), precedence=4)]
    )

    definitions = catalog.definitions_for_name("review")
    assert definitions[0].source_path == str(catalog_path)
    assert definitions[0].effective is True
    assert definitions[0].precedence > 4
    assert definitions[1].effective is False
    assert definitions[1].shadowed_by == str(catalog_path)


def test_prefix_ranking_exact_then_lexical_then_compatibility(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _empty_catalog_only(monkeypatch)
    directory = tmp_path / "macros"
    _write_macro(directory / "review.md", "body")
    _write_macro(directory / "review_long.md", "body")
    _write_macro(directory / "review_swarm.md", "one\n---\ntwo")
    catalog = load_mini_macro_target_catalog(
        locations=[
            _row(
                directory,
                names=frozenset({"review", "review_long", "review_swarm"}),
            )
        ]
    )

    matches = mini_macro_prefix_matches("review", catalog)

    assert [match.name for match in matches] == [
        "review",
        "review_long",
        "review_swarm",
    ]


def test_destination_resolution_uses_row_names_and_write_targets(
    tmp_path: Path,
) -> None:
    high = tmp_path / "high"
    low = tmp_path / "low"
    high_row = _row(high, names=frozenset({"review"}), precedence=0)
    low_row = _row(low, names=frozenset(), precedence=10)

    target = destination_target_for_name(
        low_row,
        "review",
        destinations=[high_row, low_row],
    )

    assert target.exists_here is False
    assert target.resolution.shadowed_by == str(high)
    assert target.write_path == str(low / "review.md")
