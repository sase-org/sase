"""Mini-xprompt target catalog behavior."""

from __future__ import annotations

from pathlib import Path

import yaml

from sase.ace.tui.modals import mini_xprompt_target_catalog as catalog_mod
from sase.ace.tui.modals.mini_xprompt_target_catalog import (
    default_mini_xprompt_destination,
    destination_target_for_name,
    load_mini_xprompt_target_catalog,
    mini_xprompt_prefix_matches,
    validate_name_for_destination,
)
from sase.ace.tui.modals.unified_xprompt_save_modal import UnifiedSaveLocation
from sase.ace.tui.modals.xprompt_location_modal import XPromptLocation
from sase.xprompt.models import XPrompt
from sase.xprompt.save import SaveTargetFormat


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
        location=XPromptLocation(label, str(path), location_type),  # type: ignore[arg-type]
        group=group,
        display_path=str(path),
        names=names,
        precedence=precedence,
        disabled_reason=disabled_reason,
        namespace=namespace,
        builtin=builtin,
    )


def _write_xprompt(path: Path, body: str, *, name: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if name is None:
        path.write_text(body, encoding="utf-8")
        return
    path.write_text(f"---\nname: {name}\n---\n\n{body}\n", encoding="utf-8")


def _write_config(path: Path, entries: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"xprompts": entries}), encoding="utf-8")


def _empty_catalog_only(monkeypatch) -> None:
    monkeypatch.setattr(catalog_mod, "get_all_xprompts", lambda project=None: {})
    monkeypatch.setattr(catalog_mod, "get_all_workflows", lambda project=None: {})


def test_namespace_and_storage_mapping_for_directory_and_config_targets(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "xprompts"
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
    _write_xprompt(high / "review.md", "high")
    _write_xprompt(low / "review.md", "one\n---\ntwo")
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
    catalog = load_mini_xprompt_target_catalog(locations=rows)

    definitions = catalog.definitions_for_name("review")
    assert [definition.display_path for definition in definitions]
    assert definitions[0].effective is True
    assert definitions[0].compatibility == "editable"
    assert definitions[0].shadows == str(low / "review.md")
    assert definitions[1].compatibility == "incompatible"
    assert "swarms" in (definitions[1].incompatible_reason or "")
    assert definitions[2].storage_format is SaveTargetFormat.CONFIG
    assert definitions[2].entry_name == "review"


def test_default_destination_prefers_exact_editable_then_last_used(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _empty_catalog_only(monkeypatch)
    first = tmp_path / "first"
    last = tmp_path / "last"
    _write_xprompt(first / "review.md", "body")
    first_row = _row(first, names=frozenset({"review"}), precedence=0)
    last_row = _row(last, group="Home directories", precedence=1)
    catalog = load_mini_xprompt_target_catalog(locations=[first_row, last_row])

    assert (
        default_mini_xprompt_destination(
            catalog,
            name="review",
            last_used_path=str(last),
        )
        == first_row
    )
    assert (
        default_mini_xprompt_destination(
            catalog,
            name="fresh",
            last_used_path=str(last),
        )
        == last_row
    )


def test_read_only_exact_match_falls_back_to_writable_override(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _empty_catalog_only(monkeypatch)
    readonly = tmp_path / "readonly"
    writable = tmp_path / "writable"
    _write_xprompt(readonly / "review.md", "body")
    readonly_row = _row(
        readonly,
        names=frozenset({"review"}),
        disabled_reason="read-only",
        precedence=0,
    )
    writable_row = _row(writable, precedence=1)
    catalog = load_mini_xprompt_target_catalog(locations=[readonly_row, writable_row])

    definition = catalog.effective_definition("review")
    assert definition is not None
    assert definition.compatibility == "read_only"
    assert default_mini_xprompt_destination(catalog, name="review") == writable_row


def test_catalog_only_workflows_skills_and_memory_are_incompatible(
    tmp_path: Path,
    monkeypatch,
) -> None:
    row = _row(tmp_path / "xprompts")
    monkeypatch.setattr(
        catalog_mod,
        "get_all_xprompts",
        lambda project=None: {
            "skill/review": XPrompt(
                name="skill/review",
                content="skill",
                source_path="skills/review.md",
                skill_name="review",
            ),
            "memory/obsidian": XPrompt(
                name="memory/obsidian",
                content="memory",
                source_path="memory/obsidian.md",
                memory_type="long",
            ),
        },
    )
    monkeypatch.setattr(
        catalog_mod,
        "get_all_workflows",
        lambda project=None: {},
    )

    catalog = load_mini_xprompt_target_catalog(locations=[row])

    assert catalog.effective_definition("skill/review").workflow_kind == "skill"  # type: ignore[union-attr]
    assert catalog.effective_definition("skill/review").compatibility == "incompatible"  # type: ignore[union-attr]
    assert catalog.effective_definition("memory/obsidian").workflow_kind == "memory"  # type: ignore[union-attr]


def test_prefix_ranking_exact_then_lexical_then_compatibility(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _empty_catalog_only(monkeypatch)
    directory = tmp_path / "xprompts"
    _write_xprompt(directory / "review.md", "body")
    _write_xprompt(directory / "review_long.md", "body")
    _write_xprompt(directory / "review_swarm.md", "one\n---\ntwo")
    catalog = load_mini_xprompt_target_catalog(
        locations=[
            _row(
                directory,
                names=frozenset({"review", "review_long", "review_swarm"}),
            )
        ]
    )

    matches = mini_xprompt_prefix_matches("review", catalog)

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
