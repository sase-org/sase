"""Reusable property picker and frontmatter-wrapper coverage."""

from __future__ import annotations

from sase.ace.testing import AcePage
from sase.ace.tui.modals.add_property_modal import AddableProperty, AddPropertyModal
from sase.ace.tui.modals.property_picker_modal import (
    PropertyPickerItem,
    PropertyPickerModal,
    assign_property_accelerators,
)


def test_accelerators_are_deterministic_unique_and_reserved_safe() -> None:
    items = [
        PropertyPickerItem("script", "", "scalar"),
        PropertyPickerItem("source", "", "scalar"),
        PropertyPickerItem("kind", "", "scalar"),
        PropertyPickerItem("queue", "", "scalar"),
    ]
    first = assign_property_accelerators(items)
    second = assign_property_accelerators(items)
    assert [choice.key for choice in first] == [choice.key for choice in second]
    assert len({choice.key for choice in first}) == len(items)
    assert not {choice.key for choice in first} & {"j", "k", "q"}


async def test_picker_keyboard_accelerator_guidance_and_mouse() -> None:
    results: list[str | None] = []
    properties = [
        PropertyPickerItem("timeout", "Maximum runtime.", "string", example="30s"),
        PropertyPickerItem("env", "Environment values.", "structured"),
    ]
    async with AcePage() as page:
        modal = PropertyPickerModal(
            properties,
            title="Add chop property",
            guidance="Compound values use raw YAML.",
        )
        page.app.push_screen(modal, results.append)
        await page.expect_modal("PropertyPickerModal")
        await page.wait_for(
            lambda _screen: bool(modal.query("#property-picker-guidance"))
        )
        assert (
            "Compound values"
            in modal.query_one("#property-picker-guidance").render().plain
        )
        assert "Maximum runtime" in modal._detail_text().plain
        await page.click("#property-picker-row-1")
        await page.wait_for(lambda _screen: bool(results))
    assert results == ["env"]


async def test_frontmatter_wrapper_retains_copy_and_dom_ids() -> None:
    async with AcePage() as page:
        modal = AddPropertyModal([AddableProperty("name", "Prompt name.", "scalar")])
        page.app.push_screen(modal)
        await page.expect_modal("AddPropertyModal")
        await page.wait_for(lambda _screen: bool(modal.query("#modal-title")))
        assert modal.query_one("#modal-title").render().plain == (
            "Add frontmatter property"
        )
        assert modal.query_one("#add-property-list")
        assert modal.query_one("#add-property-row-0")
