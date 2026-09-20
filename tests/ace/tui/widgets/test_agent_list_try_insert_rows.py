"""Tests for ``AgentList.try_insert_rows`` (sase-142 row-insert-without-blanking).

The contract is twofold: an insert that succeeds leaves the widget exactly as a
full ``update_list`` rebuild of the new list would (options, ids, banner chips,
and every per-row tracker), and an insert that would not is declined *before*
anything is mutated, so the caller's rebuild starts from an untouched widget.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Any

import pytest
from rich.text import Text
from textual.widgets.option_list import DuplicateID, Option

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.group_fold import GroupFoldRegistry
from sase.ace.tui.widgets.agent_list import AgentList

STANDARD = GroupingMode.STANDARD
BY_STATUS = GroupingMode.BY_STATUS


def _agent(
    name: str,
    minute: int,
    *,
    second: int = 0,
    status: str = "RUNNING",
    **fields: Any,
) -> Agent:
    return Agent(
        agent_type=fields.pop("agent_type", AgentType.RUNNING),
        cl_name="demo",
        project_file="/repo/proj.sase",
        status=status,
        start_time=datetime(2026, 4, 25, 12, minute, second),
        agent_name=name,
        raw_suffix=f"2026042512{minute:02d}{second:02d}",
        **fields,
    )


def _base() -> list[Agent]:
    return [_agent(f"node-{i:02d}", i) for i in range(6)]


def _widget(monkeypatch: pytest.MonkeyPatch) -> tuple[AgentList, list[Any]]:
    widget = AgentList()
    posted: list[Any] = []
    monkeypatch.setattr(widget, "post_message", posted.append)
    return widget, posted


def _built(
    monkeypatch: pytest.MonkeyPatch,
    agents: list[Agent],
    *,
    current_idx: int = 0,
    mode: GroupingMode = BY_STATUS,
    **kwargs: Any,
) -> AgentList:
    widget, _posted = _widget(monkeypatch)
    widget.update_list(agents, current_idx, grouping_mode=mode, **kwargs)
    return widget


def _snapshot(widget: AgentList) -> dict[str, Any]:
    """Everything a rebuild would write, minus the selection emphasis flag."""
    return {
        "ids": [option.id for option in widget.options],
        "prompts": [str(option.prompt) for option in widget.options],
        "spans": [
            list(option.prompt.spans) if isinstance(option.prompt, Text) else []
            for option in widget.options
        ],
        "disabled": [option.disabled for option in widget.options],
        "index": [widget._option_to_index[option] for option in widget.options],
        "by_id": sorted(widget._id_to_option),
        "agents": [agent.identity for agent in widget._agents],
        "row_entries": list(widget._row_entries),
        "row_by_agent_idx": dict(widget._row_by_agent_idx),
        "row_by_agent_attempt": dict(widget._row_by_agent_attempt),
        "banner_rows": {
            row: (group.group_key, group.agent_indices, group.is_collapsed)
            for row, group in widget._banner_at_row.items()
        },
        "banner_row_by_key": dict(widget._banner_row_by_key),
        "ctx": {
            idx: {k: v for k, v in ctx.items() if k != "is_selected"}
            for idx, ctx in widget._row_render_ctx.items()
        },
        "tier_styles": dict(widget._row_tier_styles),
        "target_width": widget._target_width,
        "max_left": widget._max_left,
        "max_suffix": widget._max_suffix,
        "requested_width": widget._requested_width,
    }


def _assert_matches_rebuild(
    monkeypatch: pytest.MonkeyPatch,
    widget: AgentList,
    agents: list[Agent],
    *,
    current_idx: int = 0,
    mode: GroupingMode = BY_STATUS,
    **kwargs: Any,
) -> None:
    rebuilt = _built(monkeypatch, agents, current_idx=current_idx, mode=mode, **kwargs)
    assert _snapshot(widget) == _snapshot(rebuilt)


# --- a successful insert is a rebuild, minus the rebuild ---------------------


@pytest.mark.parametrize("mode", [STANDARD, BY_STATUS])
@pytest.mark.parametrize("where", ["front", "middle", "end"])
def test_insert_leaves_the_widget_as_a_rebuild_would(
    monkeypatch: pytest.MonkeyPatch, mode: GroupingMode, where: str
) -> None:
    base = _base()
    arrival = _agent("node-2b", 2, second=30)  # sorts mid-list, as wide as the rest
    position = {"front": 0, "middle": 3, "end": len(base)}[where]
    new = [*base[:position], arrival, *base[position:]]
    widget = _built(monkeypatch, base, current_idx=2, mode=mode)
    selected = 3 if position <= 2 else 2  # node-02's index in the new list

    assert widget.try_insert_rows(new, selected, grouping_mode=mode)

    _assert_matches_rebuild(monkeypatch, widget, new, current_idx=selected, mode=mode)
    assert widget._insert_decline_reason is None


def _family_base() -> list[Agent]:
    """Plain rows around one workflow family (a parent row and one step)."""
    parent = _agent("flow", 3, agent_type=AgentType.WORKFLOW, workflow="wf")
    step = _agent(
        "flow-step",
        3,
        second=10,
        parent_timestamp=parent.raw_suffix,
        parent_workflow="wf",
    )
    return [
        _agent("node-00", 0),
        _agent("node-01", 1),
        parent,
        step,
        _agent("node-05", 5),
    ]


@pytest.mark.parametrize("mode", [STANDARD, BY_STATUS])
@pytest.mark.parametrize("position", [0, 3, 5], ids=["front", "mid-family", "end"])
def test_insert_beside_an_existing_workflow_family_is_a_rebuild(
    monkeypatch: pytest.MonkeyPatch, mode: GroupingMode, position: int
) -> None:
    # The refresh no longer names a workflow-tree change for a family that an
    # arrival merely shifts, so this is the contract that keeps that safe.
    base = _family_base()
    arrival = _agent("node-2b", 2, second=30)
    new = [*base[:position], arrival, *base[position:]]
    widget = _built(monkeypatch, base, mode=mode)
    assert any("flow-step" in str(option.prompt) for option in widget.options)
    selected = 1 if position == 0 else 0  # node-00, wherever the arrival landed

    assert widget.try_insert_rows(new, selected, grouping_mode=mode)

    _assert_matches_rebuild(monkeypatch, widget, new, current_idx=selected, mode=mode)


def test_insert_refreshes_banner_chips_instead_of_letting_them_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _base()
    widget = _built(monkeypatch, base)
    old_banner = widget.get_option_at_index(0)
    old_banner_text = str(old_banner.prompt)
    assert "6 agents" in old_banner_text

    assert widget.try_insert_rows(
        [*base, _agent("node-zz", 30)], 0, grouping_mode=BY_STATUS
    )

    assert "7 agents" in str(widget.get_option_at_index(0).prompt)
    # Banner Options are shared with the render cache; the old one must not
    # have been rewritten in place or a later cache hit would resurrect the
    # new chip under the old membership.
    assert str(old_banner.prompt) == old_banner_text


def test_insert_keeps_existing_options_before_the_insertion_point(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _base()
    widget = _built(monkeypatch, base, mode=STANDARD)
    untouched = [widget.get_option_at_index(row) for row in range(3)]  # banners + row 0

    assert widget.try_insert_rows(
        [*base, _agent("node-zz", 30)], 0, grouping_mode=STANDARD
    )

    # Rows above the new one keep their Option objects (agent rows) or are
    # replaced only because their banner chip changed.
    assert widget.get_option_at_index(2) is untouched[2]


def test_insert_keeps_the_highlight_on_the_same_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _base()
    selected = 4
    widget = _built(monkeypatch, base, current_idx=selected)
    assert widget.highlighted is not None
    before_row = widget.highlighted
    identity = base[selected].identity

    # BY_STATUS lists newest first, so a newer arrival lands above the selection.
    new = [_agent("node-zz", 30), *base]
    assert widget.try_insert_rows(new, selected + 1, grouping_mode=BY_STATUS)

    assert widget.highlighted == before_row + 1  # one new row above it
    local_idx = widget._row_entries[widget.highlighted][0]
    assert widget._agents[local_idx].identity == identity


def test_an_insert_that_fits_the_columns_requests_no_new_width(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _base()
    widget, posted = _widget(monkeypatch)
    widget.update_list(base, 0, grouping_mode=BY_STATUS)
    requested = widget._requested_width
    posted.clear()

    assert widget.try_insert_rows(
        [*base, _agent("node-zz", 30)], 0, grouping_mode=BY_STATUS
    )

    assert widget._requested_width == requested
    assert not [m for m in posted if isinstance(m, AgentList.WidthChanged)]


def test_an_insert_into_a_collapsed_group_only_refreshes_its_banner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _base()
    registry = GroupFoldRegistry()
    registry.collapse(("Running",))
    widget = _built(monkeypatch, base, fold_registry=registry)
    assert widget.option_count == 1  # just the collapsed banner

    new = [*base, _agent("node-zz", 30)]
    assert widget.try_insert_rows(
        new, 0, grouping_mode=BY_STATUS, fold_registry=registry
    )

    assert widget.option_count == 1
    assert len(widget._agents) == 7
    assert len(widget._banner_at_row[0].agent_indices) == 7
    _assert_matches_rebuild(monkeypatch, widget, new, fold_registry=registry)


def test_shifted_rows_get_unique_ids_even_after_a_removal_left_stale_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _base()
    widget = _built(monkeypatch, base)
    # ``try_remove_rows`` shifts local indices but leaves the old option ids.
    assert widget.try_remove_rows({base[2].identity})
    remaining = [agent for agent in base if agent is not base[2]]
    new = [*remaining[:3], _agent("node-2b", 2, second=30), *remaining[3:]]

    assert widget.try_insert_rows(new, 0, grouping_mode=BY_STATUS)

    ids = [option.id for option in widget.options if option.id is not None]
    assert len(ids) == len(set(ids))
    _assert_matches_rebuild(monkeypatch, widget, new)


def test_per_row_trackers_stay_usable_by_patch_and_remove(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _base()
    widget = _built(monkeypatch, base)
    arrival = _agent("node-2b", 2, second=30)
    new = [*base[:3], arrival, *base[3:]]
    assert widget.try_insert_rows(new, 0, grouping_mode=BY_STATUS)
    inserted_idx = 3

    assert widget.patch_agent_row(inserted_idx)
    assert widget.patch_agent_row(inserted_idx + 1)  # a shifted row
    assert widget.try_remove_rows({arrival.identity})

    assert [agent.identity for agent in widget._agents] == [
        agent.identity for agent in base
    ]


# --- declines leave the widget untouched -------------------------------------


def _declines(
    monkeypatch: pytest.MonkeyPatch,
    new: list[Agent],
    reason: str | None,
    *,
    base: list[Agent] | None = None,
    mode: GroupingMode = BY_STATUS,
    build_mode: GroupingMode | None = None,
    **kwargs: Any,
) -> AgentList:
    widget = _built(monkeypatch, base or _base(), mode=build_mode or mode)
    before = _snapshot(widget)
    options_before = list(widget.options)

    assert widget.try_insert_rows(new, 0, grouping_mode=mode, **kwargs) is False

    assert widget._insert_decline_reason == reason
    assert _snapshot(widget) == before
    assert list(widget.options) == options_before
    return widget


def test_a_row_wider_than_the_columns_is_declined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wide = _agent("node-with-a-much-longer-name", 30)

    _declines(monkeypatch, [*_base(), wide], "width_growth")


def test_a_new_by_status_bucket_is_declined(monkeypatch: pytest.MonkeyPatch) -> None:
    failed = _agent("node-zz", 30, status="FAILED")

    _declines(monkeypatch, [*_base(), failed], "status_membership_change")


def test_a_new_name_root_banner_is_declined(monkeypatch: pytest.MonkeyPatch) -> None:
    base = [_agent("alpha.one", 1), _agent("beta.one", 2)]
    second = _agent("alpha.two", 3)

    _declines(monkeypatch, [*base, second], "status_membership_change", base=base)


@pytest.mark.parametrize(
    "fields",
    [
        {"agent_clan": "epic-clan", "agent_clan_generation": "g1"},
        {"tree_parent_key": "clan:epic-clan:g1", "tree_depth": 1},
        {"agent_type": AgentType.WORKFLOW, "workflow": "wf"},
        {"parent_timestamp": "20260425120100", "parent_workflow": "wf"},
    ],
    ids=["clan-member", "clan-child", "workflow-parent", "workflow-child"],
)
def test_clan_and_workflow_rows_are_declined(
    monkeypatch: pytest.MonkeyPatch, fields: dict[str, Any]
) -> None:
    arrival = _agent("node-zz", 30, **fields)

    _declines(monkeypatch, [*_base(), arrival], "workflow_tree_change")


def test_an_existing_agent_that_changed_is_declined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _base()
    changed = dataclasses.replace(base[1], status="DONE")
    new = [base[0], changed, *base[2:], _agent("node-zz", 30)]

    _declines(monkeypatch, new, "panel_membership_change", base=base)


def test_an_existing_agent_that_left_or_moved_is_declined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _base()
    arrival = _agent("node-zz", 30)

    _declines(monkeypatch, [*base[:2], *base[3:], arrival], "panel_membership_change")
    _declines(
        monkeypatch,
        [base[1], base[0], *base[2:], arrival],
        "panel_membership_change",
    )


def test_an_existing_row_that_would_paint_differently_is_declined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _base()

    _declines(
        monkeypatch,
        [*base, _agent("node-zz", 30)],
        "panel_membership_change",
        marked_agents={base[1].identity},
    )


def test_selection_emphasis_alone_does_not_block_an_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _base()
    widget = _built(monkeypatch, base, current_idx=1)

    # The selection moved without a repaint (j/k only moves the highlight), so
    # the painted ``is_selected`` flags lag; that must not force a rebuild.
    assert widget.try_insert_rows(
        [*base, _agent("node-zz", 30)], 4, grouping_mode=BY_STATUS
    )


def test_unsupported_and_mismatched_grouping_modes_are_declined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    new = [*_base(), _agent("node-zz", 30)]

    _declines(
        monkeypatch,
        new,
        "unsupported_grouping",
        mode=GroupingMode.BY_DATE,
    )
    _declines(
        monkeypatch, new, "stale_grouping_mode", mode=STANDARD, build_mode=BY_STATUS
    )


@pytest.mark.parametrize("state", ["empty", "collapsed", "unchanged"])
def test_a_panel_that_is_not_an_insert_candidate_declines_quietly(
    monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    base = _base()
    widget = AgentList()
    monkeypatch.setattr(widget, "post_message", lambda _msg: None)
    if state == "collapsed":
        widget.render_collapsed(grouping_mode=BY_STATUS)
    elif state == "unchanged":
        widget.update_list(base, 0, grouping_mode=BY_STATUS)

    new = base if state == "unchanged" else [*base, _agent("node-zz", 30)]
    assert widget.try_insert_rows(new, 0, grouping_mode=BY_STATUS) is False

    assert widget._insert_decline_reason is None


def test_starting_rows_are_ignored_like_update_list_does(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _base()
    widget = _built(monkeypatch, base)
    starting = _agent("node-zz", 30, status="STARTING")

    # Nothing renderable was added, so there is nothing to insert.
    assert (
        widget.try_insert_rows([*base, starting], 0, grouping_mode=BY_STATUS) is False
    )
    assert widget._insert_decline_reason is None


# --- the option-list primitive ------------------------------------------------


def test_install_options_rejects_duplicate_ids_before_touching_the_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    widget = _built(monkeypatch, _base())
    before = list(widget.options)

    with pytest.raises(DuplicateID):
        widget.install_options([Option("a", id="x"), Option("b", id="x")])

    assert list(widget.options) == before


def test_install_options_matches_add_options_bookkeeping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    widget, _posted = _widget(monkeypatch)
    reference = AgentList()
    options = [Option("a", id="a"), Option("b"), Option("c", id="c", disabled=True)]

    widget.install_options(options)
    reference.add_options([Option("a", id="a"), Option("b"), Option("c", id="c")])

    assert [option.id for option in widget.options] == ["a", None, "c"]
    assert widget.option_count == reference.option_count == 3
    assert widget.get_option_index("c") == 2
    assert widget.get_option("a") is options[0]
