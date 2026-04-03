"""Tests for jump-to-entry hint assignment and list hint rendering."""

from sase.ace.changespec import ChangeSpec
from sase.ace.tui.actions.navigation.jump_hints import (
    JUMP_HINT_CHARS,
    build_jump_hint_maps,
)
from sase.ace.tui.bgcmd import BackgroundCommandInfo
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.agent_list import AgentList
from sase.ace.tui.widgets.bgcmd_list import BgCmdList
from sase.ace.tui.widgets.changespec_list import ChangeSpecList


def _make_changespec(name: str = "test_feature") -> ChangeSpec:
    return ChangeSpec(
        name=name,
        description="Test description",
        parent=None,
        cl=None,
        status="Ready",
        test_targets=None,
        kickstart=None,
        file_path="/tmp/test.gp",
        line_number=1,
    )


def _make_agent(cl_name: str = "test_feature") -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        raw_suffix="260101_120000",
    )


def test_build_jump_hint_maps_uses_expected_order() -> None:
    indices = [10, 11, 12]
    hint_to_index, index_to_hint = build_jump_hint_maps(indices)
    assert hint_to_index == {"1": 10, "2": 11, "3": 12}
    assert index_to_hint == {10: "1", 11: "2", 12: "3"}


def test_build_jump_hint_maps_truncates_to_hint_alphabet() -> None:
    indices = list(range(len(JUMP_HINT_CHARS) + 5))
    hint_to_index, index_to_hint = build_jump_hint_maps(indices)
    assert len(hint_to_index) == len(JUMP_HINT_CHARS)
    assert hint_to_index["1"] == 0
    assert hint_to_index["0"] == 9
    assert hint_to_index["a"] == 10
    assert hint_to_index["z"] == len(JUMP_HINT_CHARS) - 1
    assert (len(JUMP_HINT_CHARS) + 1) not in index_to_hint


def test_changespec_list_hint_marker_rendered() -> None:
    widget = ChangeSpecList()
    option = widget._format_changespec_option(
        _make_changespec(),
        is_selected=False,
        is_marked=False,
        hint_char="a",
    )
    assert "[a]" in str(option.prompt)


def test_agent_list_hint_marker_rendered() -> None:
    widget = AgentList()
    option = widget._format_agent_option(
        _make_agent(),
        index=0,
        is_selected=False,
        hint_char="b",
    )
    assert "[b]" in str(option.prompt)


def test_bgcmd_list_hint_marker_rendered() -> None:
    widget = BgCmdList()
    info = BackgroundCommandInfo(
        command="make test",
        project="myproject",
        workspace_num=1,
        workspace_dir="/tmp/ws1",
        started_at="2026-01-01T12:00:00",
    )
    option = widget._format_bgcmd_option(
        slot=1,
        info=info,
        is_selected=False,
        is_running=True,
        hint_char="9",
    )
    assert "[9]" in str(option.prompt)
