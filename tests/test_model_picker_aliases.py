"""Tests for model picker alias selection behavior."""

from rich.text import Text
from textual.containers import Container
from textual.widgets import Input, OptionList, Static

from sase.ace.tui.modals.model_picker_modal import (
    CUSTOM_SENTINEL,
    ModelPickerModal,
    alias_reference_rejection,
)
from sase.ace.tui.modals.model_picker_options import rows_to_options
from sase.ace.tui.modals.model_picker_rows import (
    _alias_disabled_reason,
    build_model_rows,
)
from tests._model_picker_modal_helpers import (
    ModelPickerTestApp,
    StyledModelPickerTestApp,
    make_alias_context,
)
from tests._models_panel_helpers import make_alias_view, make_override


def test_alias_context_builds_styled_rows_after_models() -> None:
    context = make_alias_context(target="medium_phase_worker")
    rows = build_model_rows(
        include_default_option=False,
        alias_context=context,
    )

    provider_index = next(
        index for index, row in enumerate(rows) if row.kind == "provider"
    )
    alias_index = next(
        index for index, row in enumerate(rows) if row.kind == "alias_header"
    )
    assert provider_index == 0
    assert alias_index > provider_index
    assert [row.option_id for row in rows[alias_index : alias_index + 16]] == [
        "__header_aliases__",
        "@default",
        "@coder",
        "@epic_lander",
        "@big_epic_lander",
        "@task_worker",
        "@xsmall_phase_worker",
        "@small_phase_worker",
        "@medium_phase_worker",
        "@large_phase_worker",
        "@xlarge_phase_worker",
        "@smartest",
        "@smart",
        "@cheap",
        "@cheaper",
        "@cheapest",
    ]
    assert rows[-1].option_id == CUSTOM_SENTINEL
    alias_options = [
        option
        for option in rows_to_options(rows[alias_index : alias_index + 16])
        if option is not None and str(option.id).startswith("@")
    ]
    assert all(isinstance(option.prompt, Text) for option in alias_options)
    assert {option.prompt.plain.index("→") for option in alias_options} == {27}
    coder = next(option for option in alias_options if option.id == "@coder")
    assert "CODEX(gpt-5.6-sol)" in coder.prompt.plain
    assert any(span.style == "bold #87D7FF" for span in coder.prompt.spans)


def test_followup_default_stays_before_models_and_aliases() -> None:
    rows = build_model_rows(alias_context=make_alias_context())

    assert rows[0].kind == "default"
    provider_index = next(
        index for index, row in enumerate(rows) if row.kind == "provider"
    )
    alias_index = next(
        index for index, row in enumerate(rows) if row.kind == "alias_header"
    )
    assert 0 < provider_index < alias_index < len(rows) - 1
    assert rows[-1].kind == "custom"


def test_default_override_alias_row_labels_snapshot_semantics() -> None:
    context = make_alias_context(
        target="coder",
        operation="temporary",
        views=[
            make_alias_view(
                "default",
                "default",
                provider="codex",
                model="o3",
                override=make_override(),
            )
        ],
    )

    row = next(
        row
        for row in build_model_rows(
            include_default_option=False,
            alias_context=context,
        )
        if row.option_id == "@default"
    )

    assert row.provider == "codex"
    assert row.model_id == "o3"
    assert row.rendered_label is not None
    assert "override now · snapshot" in row.rendered_label.plain


def test_alias_dependency_guard_covers_implicit_and_configured_chains() -> None:
    views = [
        make_alias_view("default", "default"),
        make_alias_view("coder", "role"),
        make_alias_view("codex_coder", "provider_coder"),
        make_alias_view("epic_lander", "role"),
        make_alias_view("big_epic_lander", "role"),
        make_alias_view("task_worker", "role"),
        make_alias_view("xsmall_phase_worker", "role"),
        make_alias_view("small_phase_worker", "role"),
        make_alias_view("medium_phase_worker", "role"),
        make_alias_view("large_phase_worker", "role"),
        make_alias_view("xlarge_phase_worker", "role"),
        make_alias_view("smartest", "role"),
        make_alias_view("smart", "role"),
        make_alias_view("cheap", "role"),
        make_alias_view("cheaper", "role"),
        make_alias_view("cheapest", "role"),
        make_alias_view("hop_a", "user", configured=True, configured_value="@hop_b"),
        make_alias_view("hop_b", "user", configured=True, configured_value="@coder"),
        make_alias_view(
            "cycle_a", "user", configured=True, configured_value="@cycle_b"
        ),
        make_alias_view(
            "cycle_b", "user", configured=True, configured_value="@cycle_a"
        ),
        make_alias_view(
            "safe", "user", configured=True, configured_value="claude/haiku"
        ),
    ]
    coder_context = make_alias_context(target="coder", views=views)
    default_context = make_alias_context(target="default", views=views)
    smartest_context = make_alias_context(target="smartest", views=views)

    assert _alias_disabled_reason(coder_context, "coder") == "current alias"
    assert _alias_disabled_reason(coder_context, "hop_a") == "would create a cycle"
    assert _alias_disabled_reason(coder_context, "cycle_a") == ("would create a cycle")
    assert _alias_disabled_reason(coder_context, "safe") is None
    # provider_coder -> coder -> default and big_epic_lander -> smartest are
    # implicit chains.
    assert _alias_disabled_reason(default_context, "codex_coder") == (
        "would create a cycle"
    )
    assert _alias_disabled_reason(default_context, "big_epic_lander") is None
    assert _alias_disabled_reason(default_context, "large_phase_worker") == (
        "would create a cycle"
    )
    assert _alias_disabled_reason(default_context, "medium_phase_worker") == (
        "would create a cycle"
    )
    assert _alias_disabled_reason(smartest_context, "big_epic_lander") == (
        "would create a cycle"
    )
    assert _alias_disabled_reason(smartest_context, "xlarge_phase_worker") == (
        "would create a cycle"
    )
    medium_context = make_alias_context(target="medium_phase_worker", views=views)
    assert _alias_disabled_reason(medium_context, "medium_phase_worker") == (
        "current alias"
    )
    assert _alias_disabled_reason(medium_context, "small_phase_worker") is None
    assert _alias_disabled_reason(medium_context, "large_phase_worker") is None


def test_alias_dependency_guard_handles_long_chains() -> None:
    views = [make_alias_view("target", "user")]
    for index in range(40):
        dependency = "target" if index == 39 else f"hop_{index + 1}"
        views.append(
            make_alias_view(
                f"hop_{index}",
                "user",
                configured=True,
                configured_value=f"@{dependency}",
            )
        )
    context = make_alias_context(target="target", views=views)

    assert _alias_disabled_reason(context, "hop_0") == "would create a cycle"


def test_temporary_alias_guard_disables_only_self() -> None:
    views = [
        make_alias_view("target", "user"),
        make_alias_view(
            "cycle_a", "user", configured=True, configured_value="@cycle_b"
        ),
        make_alias_view(
            "cycle_b", "user", configured=True, configured_value="@cycle_a"
        ),
    ]
    context = make_alias_context(target="target", operation="temporary", views=views)

    assert _alias_disabled_reason(context, "target") == "current alias"
    assert _alias_disabled_reason(context, "cycle_a") is None


def test_free_form_alias_guard_rejects_unknown_and_unsafe_references() -> None:
    context = make_alias_context(target="coder")

    assert alias_reference_rejection(context, "@missing") == "unknown alias"
    assert alias_reference_rejection(context, "@coder") == "current alias"
    assert alias_reference_rejection(context, "@default") is None
    assert alias_reference_rejection(context, "@default@medium") is None
    assert alias_reference_rejection(context, "@default@turbo") == "unknown alias"
    assert alias_reference_rejection(context, "claude/opus") is None


async def test_alias_picker_filters_all_alias_fields_and_returns_raw_token() -> None:
    captured: list[str | None] = []
    context = make_alias_context(target="medium_phase_worker")

    async with ModelPickerTestApp().run_test() as pilot:
        modal = ModelPickerModal(
            include_default_option=False,
            alias_context=context,
        )
        pilot.app.push_screen(modal, captured.append)
        await pilot.pause()
        filter_input = modal.query_one("#model-picker-filter", Input)
        assert filter_input.placeholder == "Filter aliases, providers, or models..."

        for query in ("@coder", "coder", "implementation follow-up", "gpt-5.6"):
            filter_input.value = query
            await pilot.pause()
            ids = {
                option.id
                for option in modal.query_one("#model-picker-list", OptionList).options
            }
            assert "@coder" in ids
            assert "__empty__" not in ids

        option_list = modal.query_one("#model-picker-list", OptionList)
        option_list.highlighted = option_list.get_option_index("@coder")
        modal.action_select_model()
        await pilot.pause()

    assert captured == ["@coder"]


async def test_alias_only_no_match_uses_contextual_empty_state() -> None:
    async with ModelPickerTestApp().run_test() as pilot:
        modal = ModelPickerModal(
            include_default_option=False,
            alias_context=make_alias_context(),
        )
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal.query_one("#model-picker-filter", Input).value = "not-a-target"
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        empty = option_list.get_option("__empty__")
        assert str(empty.prompt) == "  No matching aliases or models"
        assert option_list.get_option(CUSTOM_SENTINEL) is not None


async def test_alias_disabled_rows_are_searchable_and_skipped_by_navigation() -> None:
    context = make_alias_context(target="coder")
    async with ModelPickerTestApp().run_test() as pilot:
        modal = ModelPickerModal(
            include_default_option=False,
            alias_context=context,
        )
        pilot.app.push_screen(modal)
        await pilot.pause()
        filter_input = modal.query_one("#model-picker-filter", Input)
        filter_input.value = "@coder"
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        coder = option_list.get_option("@coder")
        assert coder.disabled is True
        assert "current alias" in str(coder.prompt)
        assert "@coder" not in modal._visible_selectable_option_ids()
        modal.action_jump_to_entry()
        assert "@coder" not in modal._model_jump_id_to_hint


async def test_alias_picker_narrow_geometry_keeps_single_line_rows_and_footer() -> None:
    long_name = "very_long_custom_alias_name_that_must_truncate"
    context = make_alias_context(
        target="medium_phase_worker",
        views=[
            make_alias_view(
                long_name,
                "user",
                configured=True,
                configured_value="opencode/anthropic/claude-sonnet-4-5",
                provider="opencode",
                model="anthropic/claude-sonnet-4-5",
            ),
            make_alias_view("medium_phase_worker", "role"),
        ],
    )
    async with StyledModelPickerTestApp().run_test(size=(60, 30)) as pilot:
        modal = ModelPickerModal(
            include_default_option=False,
            alias_context=context,
        )
        pilot.app.push_screen(modal)
        await pilot.pause()

        container = modal.query_one("#model-picker-container", Container)
        footer = modal.query_one("#model-picker-footer", Static)
        option = modal.query_one("#model-picker-list", OptionList).get_option(
            f"@{long_name}"
        )
        assert container.region.x >= 0
        assert container.region.right <= modal.size.width
        assert footer.region.bottom <= modal.size.height
        assert isinstance(option.prompt, Text)
        assert "\n" not in option.prompt.plain
        assert option.prompt.no_wrap is True
