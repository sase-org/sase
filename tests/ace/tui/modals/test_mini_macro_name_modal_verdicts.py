"""Verdict and redefinition-warning tests for the mini-macro name modal.

Split from ``test_mini_macro_name_modal``; shared helpers live in
``_mini_macro_name_modal_helpers`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path

from sase.ace.testing.wait import wait_for as wait_for_pilot
from sase.ace.tui.modals import mini_macro_name_modal as modal_mod
from sase.ace.tui.modals import mini_macro_target_catalog as catalog_mod
from sase.ace.tui.modals.mini_macro_name_modal import (
    MiniMacroNameModal,
    MiniMacroNameResult,
)
from sase.ace.tui.modals.mini_macro_redefinition import macro_redefinition
from sase.ace.tui.modals.mini_macro_redefinition import macro_redefinition_warning
from sase.ace.tui.modals.mini_macro_target_catalog import (
    MiniMacroTargetCatalog,
    load_mini_macro_target_catalog,
)
from sase.macro.models import Macro
from tests.ace.tui.modals._mini_macro_name_modal_helpers import (
    MiniMacroNameModalApp,
    make_definition,
    make_row,
    wait_for_verdict,
)


async def test_fork_verdict_suggests_shift_tab_to_other_destination(
    tmp_path: Path,
) -> None:
    high = tmp_path / "high"
    low = tmp_path / "low"
    high_row = make_row(high, names=frozenset({"review"}), precedence=0)
    low_row = make_row(low, precedence=10)
    definition = make_definition(
        "review",
        high / "review.md",
        location_path=str(high),
        precedence=0,
    )
    app = MiniMacroNameModalApp()

    async with app.run_test(size=(110, 30)) as pilot:
        app.push_screen(
            MiniMacroNameModal(
                MiniMacroTargetCatalog(
                    definitions=(definition,),
                    destinations=(high_row, low_row),
                ),
                low_row,
                initial_name="review",
            )
        )
        modal = app.screen
        assert isinstance(modal, MiniMacroNameModal)
        verdict = await wait_for_verdict(pilot, modal, "would be shadowed by")
        assert "already exists in" in verdict
        assert "⇧tab to edit it in Test instead" in verdict


def test_build_verdict_describes_shadowed_create(tmp_path: Path) -> None:
    high = make_row(tmp_path / "high", names=frozenset({"review"}), precedence=0)
    low = make_row(tmp_path / "low", precedence=10)
    catalog = MiniMacroTargetCatalog(definitions=(), destinations=(high, low))
    verdict = modal_mod._build_mini_macro_name_analysis(
        catalog,
        "review",
        low,
    ).verdict

    assert verdict.action == "create"
    assert verdict.kind == "warning"
    assert "would be shadowed by" in verdict.message


async def test_shadowed_destination_edit_is_a_warning_and_keeps_edit_action(
    tmp_path: Path,
) -> None:
    high = tmp_path / "high"
    low = tmp_path / "low"
    high_row = make_row(high, names=frozenset({"review"}), precedence=0)
    low_row = make_row(low, names=frozenset({"review"}), precedence=10)
    active = make_definition(
        "review",
        high / "review.md",
        location_path=str(high),
        precedence=0,
    )
    shadowed = make_definition(
        "review",
        low / "review.md",
        effective=False,
        location_path=str(low),
        precedence=10,
    )
    catalog = MiniMacroTargetCatalog(
        definitions=(active, shadowed),
        destinations=(high_row, low_row),
    )
    results: list[MiniMacroNameResult | None] = []
    app = MiniMacroNameModalApp()

    async with app.run_test(size=(110, 30)) as pilot:
        app.push_screen(
            MiniMacroNameModal(catalog, low_row, initial_name="review"),
            results.append,
        )
        modal = app.screen
        assert isinstance(modal, MiniMacroNameModal)
        verdict = await wait_for_verdict(pilot, modal, "is shadowed by")
        assert "edits here won't take effect" in verdict
        await pilot.press("enter")
        await wait_for_pilot(pilot, lambda: bool(results), timeout=8.0)

    result = results[0]
    assert result is not None
    assert result.action == "edit"
    assert result.save_warning is not None
    assert "is shadowed by" in result.save_warning


def test_fork_warning_when_destination_wins_counts_other_definitions(
    tmp_path: Path,
) -> None:
    destination = make_row(
        tmp_path / "destination",
        names=frozenset(),
        precedence=0,
    )
    active_row = make_row(
        tmp_path / "active",
        names=frozenset({"review"}),
        precedence=10,
    )
    other_row = make_row(
        tmp_path / "other",
        names=frozenset({"review"}),
        precedence=20,
    )
    active = make_definition(
        "review",
        tmp_path / "active" / "review.md",
        location_path=str(tmp_path / "active"),
        precedence=10,
    )
    other = make_definition(
        "review",
        tmp_path / "other" / "review.md",
        effective=False,
        location_path=str(tmp_path / "other"),
        precedence=20,
    )
    catalog = MiniMacroTargetCatalog(
        definitions=(active, other),
        destinations=(destination, active_row, other_row),
    )

    verdict = modal_mod._build_mini_macro_name_analysis(
        catalog,
        "review",
        destination,
    ).verdict

    assert verdict.action == "fork"
    assert verdict.kind == "warning"
    assert "(+1 more)" in verdict.message
    assert "will override it" in verdict.message


def test_read_only_override_warning_uses_active_outside_rows_copy(
    tmp_path: Path,
) -> None:
    destination = make_row(tmp_path / "destination", precedence=0)
    active = make_definition(
        "review",
        tmp_path / "legacy" / "review.md",
        compatibility="read_only",
        location_path=None,
    )
    catalog = MiniMacroTargetCatalog(
        definitions=(active,),
        destinations=(destination,),
    )

    verdict = modal_mod._build_mini_macro_name_analysis(
        catalog,
        "review",
        destination,
    ).verdict

    assert verdict.action == "override"
    assert "saving to" in verdict.message
    assert "adds another definition" in verdict.message


def test_default_config_loader_id_uses_override_warning(
    tmp_path: Path, monkeypatch
) -> None:
    builtin_path = tmp_path / "default_config.yml"
    builtin_path.write_text(
        "macros:\n  review:\n    content: built in\n", encoding="utf-8"
    )
    destination_path = tmp_path / "user.yml"
    destination_path.write_text("macros: {}\n", encoding="utf-8")
    builtin = make_row(
        builtin_path,
        names=frozenset({"review"}),
        location_type="config",
        group="Built-in (dev)",
        precedence=10,
    )
    destination = make_row(
        destination_path,
        location_type="config",
        group="User config",
        precedence=0,
    )
    monkeypatch.setattr(
        catalog_mod,
        "get_all_macros",
        lambda project=None: {
            "review": Macro(
                name="review", content="built in", source_path="default_config"
            )
        },
    )
    monkeypatch.setattr(catalog_mod, "get_all_workflows", lambda project=None: {})
    monkeypatch.setattr(
        catalog_mod, "definition_file_for_source", lambda _: builtin_path
    )

    catalog = load_mini_macro_target_catalog(locations=[builtin, destination])
    warning = macro_redefinition_warning(
        macro_redefinition(catalog, "review", destination)
    )

    assert warning is not None
    assert f"already exists in {builtin.display_path}:review" in warning
    assert f"saving to {destination.display_path} will override it" in warning
