"""Pure metadata and ordering coverage for the AXE add flow."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from sase.ace.tui.modals.axe_add_modals import (
    AxeAddChooserModal,
    AxeScriptPickerModal,
    stable_chop_name,
    validate_axe_new_entry_identity,
)


def test_add_chooser_order_follows_context() -> None:
    contextual = AxeAddChooserModal("hooks")
    empty = AxeAddChooserModal(None)
    assert [choice.item.name for choice in contextual.choices] == [
        "chop",
        "lumberjack",
    ]
    assert [choice.item.name for choice in empty.choices] == [
        "lumberjack",
        "chop",
    ]


def test_stable_script_name_and_exact_duplicate_validation() -> None:
    assert stable_chop_name("/tmp/bin/sase_chop_refresh.docs") == "refresh.docs"
    assert (
        validate_axe_new_entry_identity(
            kind="chop",
            lumberjack="hooks.main",
            name="space name",
            script="sase_chop_space",
            base_chop_identities={("hooks.main", "other")},
        )
        is None
    )
    assert "already exists" in (
        validate_axe_new_entry_identity(
            kind="chop",
            lumberjack="hooks.main",
            name="space name",
            script="sase_chop_space",
            base_chop_identities={("hooks.main", "space name")},
        )
        or ""
    )
    # Generated display identities are intentionally absent from the base set.
    assert (
        validate_axe_new_entry_identity(
            kind="chop",
            lumberjack="hooks.main",
            name="space name[target]",
            script="custom.script",
            base_chop_identities={("hooks.main", "space name")},
        )
        is None
    )


def test_script_picker_carries_resolution_source_and_custom_choice() -> None:
    inventory = cast(
        Any,
        SimpleNamespace(
            available_scripts=(
                SimpleNamespace(
                    name="sase_chop_docs",
                    executable="/venv/bin/sase_chop_docs",
                    source="python_bin",
                    configured=True,
                ),
            )
        ),
    )
    modal = AxeScriptPickerModal(inventory)
    assert modal.script_choices[0].executable == "/venv/bin/sase_chop_docs"
    assert modal.script_choices[0].source == "python_bin"
    assert modal.script_choices[0].configured is True
    assert modal.script_choices[-1].custom is True
