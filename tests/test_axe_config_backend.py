"""Contract tests for the typed Rust-backed AXE config facade."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from sase.axe.config import load_axe_config
from sase.axe.config_backend import (
    AxeEntrySelector,
    AxeFieldOperation,
    compose_axe_config,
    plan_axe_entry_edit,
)
from sase.config.core import ConfigLayer


def _layers(target: Path) -> list[ConfigLayer]:
    return [
        ConfigLayer(
            name="default",
            path=None,
            exists=True,
            list_strategy="concatenate",
            data={
                "axe": {
                    "lumberjacks": {
                        "checks.main": {
                            "description": "Run primary checks",
                            "interval": 10,
                            "chops": [
                                {
                                    "name": "release.check",
                                    "description": "Check release readiness",
                                    "script": "sase_chop_release",
                                },
                                {
                                    "name": "space name",
                                    "description": "Check spaced identities",
                                    "script": "sase_chop_space",
                                },
                            ],
                        }
                    }
                }
            },
        ),
        ConfigLayer(
            name="overlay:work.yml",
            path=str(target),
            exists=True,
            list_strategy="concatenate",
            data={
                "axe": {
                    "lumberjacks": {
                        "checks.main": {
                            "chops": {"release.check": {"description": "overlay"}}
                        }
                    }
                }
            },
        ),
    ]


def test_exact_inventory_and_sparse_plan_preserve_dotted_keys(tmp_path: Path) -> None:
    target = tmp_path / "sase_work.yml"
    target.write_text(
        "# keep\naxe:\n  lumberjacks:\n    checks.main:\n"
        "      chops:\n        release.check:\n          description: overlay\n",
        encoding="utf-8",
    )
    composition = compose_axe_config(_layers(target))
    selector = AxeEntrySelector.chop_entry("checks.main", "release.check")
    assert [
        item.selector.chop
        for item in composition.entries
        if item.selector.kind == "chop" and not item.generated
    ] == ["release.check", "space name"]
    entry = composition.entry(selector)
    assert entry is not None
    assert entry.effective["script"] == "sase_chop_release"
    assert (
        composition.entry(AxeEntrySelector.chop_entry("checks.main", "space name"))
        is not None
    )
    assert any(
        item.key_path[-2:] == ("release.check", "description")
        for item in entry.field_provenance
    )

    plan = plan_axe_entry_edit(
        composition,
        selector,
        "overlay:work.yml",
        [
            AxeFieldOperation.set_value(("enabled",), False),
            AxeFieldOperation.unset(("description",)),
        ],
        schema={"type": "object"},
        use_chezmoi=False,
    )
    assert plan.edit_plan.write_plan.key_path[-2:] == (
        "chops",
        "release.check",
    )
    written = yaml.safe_load(plan.new_text)
    contribution = written["axe"]["lumberjacks"]["checks.main"]["chops"]
    assert contribution == {"release.check": {"enabled": False}}
    assert "# keep" in plan.new_text
    assert plan.effective_preview.after["script"] == "sase_chop_release"
    assert (
        plan.candidate_composition.effective_config == plan.edit_plan.candidate_config
    )


def test_legacy_list_promotion_rewrites_only_chops_subtree(tmp_path: Path) -> None:
    target = tmp_path / "sase.yml"
    target.write_text(
        "# outside\naxe:\n  max_hook_runners: 4  # outside-field\n"
        "  lumberjacks:\n    checks:\n"
        "      description: Run promotion checks\n"
        "      interval: 5\n"
        "      chops:\n        - name: base\n          description: Base check\n"
        "        - name: other\n          description: Other check\n"
        "          enabled: true\n",
        encoding="utf-8",
    )
    layer = ConfigLayer(
        name="user",
        path=str(target),
        exists=True,
        list_strategy="replace",
        data=yaml.safe_load(target.read_text(encoding="utf-8")),
    )
    composition = compose_axe_config([layer])
    plan = plan_axe_entry_edit(
        composition,
        AxeEntrySelector.chop_entry("checks", "base"),
        "user",
        [AxeFieldOperation.set_value(("description",), "promoted")],
        schema={"type": "object"},
        use_chezmoi=False,
    )
    assert plan.promoted_legacy_list
    assert plan.edit_plan.write_plan.key_path[-1] == "chops"
    assert "# outside" in plan.new_text
    assert "# outside-field" in plan.new_text
    data = yaml.safe_load(plan.new_text)
    assert data["axe"]["lumberjacks"]["checks"]["chops"] == {
        "base": {"name": "base", "description": "promoted"},
        "other": {
            "name": "other",
            "description": "Other check",
            "enabled": True,
        },
    }


def test_runtime_uses_same_composition_as_preview(tmp_path: Path) -> None:
    target = tmp_path / "sase_work.yml"
    target.write_text("", encoding="utf-8")
    layers = _layers(target)
    composition = compose_axe_config(layers)
    with (
        patch("sase.axe.config.load_merged_config", return_value={}),
        patch("sase.axe.config.load_config_layers", return_value=layers),
    ):
        runtime = load_axe_config()
    runtime_chop = runtime.lumberjacks["checks.main"].chops[0]
    effective = composition.entry(
        AxeEntrySelector.chop_entry("checks.main", "release.check")
    )
    assert effective is not None
    assert runtime_chop.script == effective.effective["script"]
    assert runtime_chop.description == effective.effective["description"]
    assert runtime_chop.description_summary == "overlay"
    assert runtime_chop.description_body == ""


def test_composition_enforces_description_shape() -> None:
    composition = compose_axe_config(
        [
            ConfigLayer(
                name="user",
                path=None,
                exists=True,
                list_strategy="replace",
                data={
                    "axe": {
                        "lumberjacks": {
                            "checks": {
                                "description": "Run checks\nMissing separator",
                                "interval": 10,
                                "chops": {},
                            }
                        }
                    }
                },
            )
        ]
    )

    assert {
        (item.code, item.path)
        for item in composition.diagnostics
        if item.code == "description_body_separator_required"
    } == {
        (
            "description_body_separator_required",
            "axe.lumberjacks.checks.description",
        )
    }


def test_mutation_planning_enforces_description_shape(tmp_path: Path) -> None:
    target = tmp_path / "sase_work.yml"
    target.write_text("", encoding="utf-8")
    composition = compose_axe_config(_layers(target))

    plan = plan_axe_entry_edit(
        composition,
        AxeEntrySelector.chop_entry("checks.main", "release.check"),
        "overlay:work.yml",
        [
            AxeFieldOperation.set_value(
                ("description",),
                "Check release readiness\nMissing separator",
            )
        ],
        schema={"type": "object"},
        use_chezmoi=False,
    )

    assert not plan.is_valid
    assert {item.code for item in plan.axe_diagnostics} == {
        "description_body_separator_required"
    }
