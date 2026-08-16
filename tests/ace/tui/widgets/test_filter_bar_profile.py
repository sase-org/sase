"""Widget-level tests for profile-driven ``FilterBar`` configuration."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import OptionList

from sase.ace.query_profile import compile_query_profile
from sase.ace.query_profile.profiles import beads_query_schema, files_query_schema
from sase.ace.tui.widgets.filter_bar import FilterBar

_BEADS_PROFILE = compile_query_profile(beads_query_schema())
_FILES_PROFILE = compile_query_profile(files_query_schema())


class _FilterBarApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, bar: FilterBar) -> None:
        super().__init__()
        self._bar = bar

    def compose(self) -> ComposeResult:
        yield self._bar


def _option_labels(option_list: OptionList) -> list[str]:
    return [
        option_list.get_option_at_index(index).prompt.plain
        for index in range(option_list.option_count)
    ]


def test_configure_from_profile_derives_dialect_without_class_declarations() -> None:
    bar = FilterBar(profile=_BEADS_PROFILE)
    assert dict(bar.KEY_COMPLETIONS)["type"] == "plan, phase, task, flag"
    assert "id" not in dict(bar.KEY_COMPLETIONS)  # search-only field: not filterable
    assert set(bar.STATIC_VALUE_COMPLETIONS["type"]) == {
        "flag",
        "phase",
        "plan",
        "task",
    }
    assert "assignee" not in bar.STATIC_VALUE_COMPLETIONS  # plain string field
    assert bar.NEGATABLE_KEYS == frozenset(_BEADS_PROFILE.negatable_fields())
    assert bar.REPEATABLE_VALUE_KINDS == frozenset(_BEADS_PROFILE.repeatable_fields())
    assert bar.FREE_TEXT_HINT == "id, title, body, refs (AND)"


def test_files_profile_derives_negatable_keys() -> None:
    bar = FilterBar(profile=_FILES_PROFILE)
    assert bar.NEGATABLE_KEYS == frozenset(_FILES_PROFILE.negatable_fields())


async def test_key_completion_lists_profile_fields_alphabetically() -> None:
    app = _FilterBarApp(FilterBar(profile=_BEADS_PROFILE))
    async with app.run_test() as pilot:
        bar = app.query_one(FilterBar)
        bar.open("")
        await pilot.pause()
        completion = app.query_one(f"#{bar.COMPLETION_ID}", OptionList)
        labels = _option_labels(completion)
        # Alphabetical by key (the profile's canonical field order), plus the
        # free-text hint row.
        assert labels[0].startswith("assignee:")
        assert any(label.startswith("free text") for label in labels)


async def test_enum_value_completion_uses_profile_static_values() -> None:
    app = _FilterBarApp(FilterBar(profile=_BEADS_PROFILE))
    async with app.run_test() as pilot:
        bar = app.query_one(FilterBar)
        bar.open("type:")
        await pilot.pause()
        completion = app.query_one(f"#{bar.COMPLETION_ID}", OptionList)
        labels = _option_labels(completion)
        assert {label.split()[0] for label in labels} == {
            "flag",
            "phase",
            "plan",
            "task",
        }


async def test_negation_completion_omits_non_negatable_profile_keys() -> None:
    app = _FilterBarApp(FilterBar(profile=_BEADS_PROFILE))
    async with app.run_test() as pilot:
        bar = app.query_one(FilterBar)
        bar.open("-")
        await pilot.pause()
        completion = app.query_one(f"#{bar.COMPLETION_ID}", OptionList)
        key_labels = [
            label
            for label in _option_labels(completion)
            if not label.startswith("free")
        ]
        keys = {label.split(":")[0].removeprefix("-") for label in key_labels}
        assert keys == set(_BEADS_PROFILE.negatable_fields())
