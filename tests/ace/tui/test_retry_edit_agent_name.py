"""Tests for Agents-tab retry-edit name rewriting."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import Mock, patch

import pytest

from sase.agent.retry_prompt import rewrite_retry_prompt_name
from sase.ace.tui.actions.agent_workflow._entry_name_prompts import (
    prepare_kill_and_edit_prompt,
)
from sase.ace.tui.actions.agent_workflow._entry_points import (
    EntryPointsMixin,
    _force_name_reuse_in_prompt,
    _rewrite_retry_prompt_name,
)


@dataclass
class _Agent:
    raw_prompt: str | None
    agent_name: str | None = "foo"
    project_file: str = "/tmp/proj/proj.sase"
    cl_name: str = "branch"
    is_project_agent: bool = False
    status: str = "DONE"
    pid: int | None = None
    workspace_num: int | None = None

    def get_raw_xprompt_content(self) -> str | None:
        return self.raw_prompt


class _App(EntryPointsMixin):
    def __init__(self, agent: _Agent) -> None:
        self.agent = agent
        self.launched: tuple[str, str, str, bool] | None = None
        self.notifications: list[tuple[str, str | None]] = []

    def _get_selected_agent(self) -> _Agent:
        return self.agent

    def _edit_and_relaunch_agent(
        self,
        raw_prompt: str,
        project_file: str,
        cl_name: str,
        is_project_agent: bool,
    ) -> None:
        self.launched = (raw_prompt, project_file, cl_name, is_project_agent)

    def notify(self, message: str, *, severity: str | None = None) -> None:
        self.notifications.append((message, severity))

    def _dismiss_done_agent(self, agent: _Agent) -> None:
        return None


def test_rewrite_retry_prompt_prepends_name_when_missing() -> None:
    assert _rewrite_retry_prompt_name("Do work", "foo.r0") == "%id:foo.r0\nDo work"


def test_rewrite_retry_prompt_replaces_percent_name() -> None:
    assert (
        _rewrite_retry_prompt_name("%id:foo\nDo work", "foo.r0")
        == "%id:foo.r0\nDo work"
    )


def test_rewrite_retry_prompt_replaces_percent_n() -> None:
    assert (
        _rewrite_retry_prompt_name("%i:foo\nDo work", "foo.r0") == "%id:foo.r0\nDo work"
    )


def test_rewrite_retry_prompt_replaces_template_name() -> None:
    assert (
        _rewrite_retry_prompt_name("%id:@.cld\nDo work", "0.cld.r0")
        == "%id:0.cld.r0\nDo work"
    )


def test_rewrite_retry_prompt_ignores_fenced_and_disabled_name_directives() -> None:
    prompt = (
        "```\n%id:fenced\n```\n"
        "%xprompts_enabled:false\n"
        "%i:disabled\n"
        "%xprompts_enabled:true\n"
        "Do work"
    )
    assert _rewrite_retry_prompt_name(prompt, "foo.r0") == f"%id:foo.r0\n{prompt}"


def test_rewrite_retry_prompt_can_prepend_n_alias() -> None:
    assert (
        rewrite_retry_prompt_name("Do work", "foo.r0", directive_alias="i")
        == "%i:foo.r0\nDo work"
    )


def test_rewrite_retry_prompt_can_replace_percent_name_with_n_alias() -> None:
    assert (
        rewrite_retry_prompt_name(
            "%id:foo\nDo work",
            "foo.r0",
            directive_alias="i",
        )
        == "%i:foo.r0\nDo work"
    )


def test_rewrite_retry_prompt_can_replace_percent_n_with_n_alias() -> None:
    assert (
        rewrite_retry_prompt_name("%i:foo\nDo work", "foo.r0", directive_alias="i")
        == "%i:foo.r0\nDo work"
    )


def test_rewrite_retry_prompt_n_alias_ignores_fenced_and_disabled_directives() -> None:
    prompt = (
        "```\n%id:fenced\n```\n"
        "%xprompts_enabled:false\n"
        "%i:disabled\n"
        "%xprompts_enabled:true\n"
        "Do work"
    )
    assert (
        rewrite_retry_prompt_name(prompt, "foo.r0", directive_alias="i")
        == f"%i:foo.r0\n{prompt}"
    )


def test_force_name_reuse_rewrites_colon_name_directive() -> None:
    assert _force_name_reuse_in_prompt("%id:foo\nDo work") == "%id:!foo\nDo work"


def test_force_name_reuse_rewrites_colon_alias_directive() -> None:
    assert _force_name_reuse_in_prompt("%i:foo\nDo work") == "%i:!foo\nDo work"


def test_force_name_reuse_rewrites_parenthesized_name_directive() -> None:
    assert _force_name_reuse_in_prompt("%id(foo)\nDo work") == "%id(!foo)\nDo work"


def test_force_name_reuse_rewrites_backtick_name_directive() -> None:
    assert _force_name_reuse_in_prompt("%id:`foo`\nDo work") == "%id:`!foo`\nDo work"


def test_force_name_reuse_leaves_already_forced_name_directive() -> None:
    assert _force_name_reuse_in_prompt("%id:!foo\nDo work") == "%id:!foo\nDo work"


def test_force_name_reuse_leaves_template_without_replacement() -> None:
    assert _force_name_reuse_in_prompt("%id:@.cld\nDo work") == ("%id:@.cld\nDo work")


def test_force_name_reuse_replaces_template_with_concrete_name() -> None:
    assert _force_name_reuse_in_prompt("%id:@.cld\nDo work", "0.cld") == (
        "%id:!0.cld\nDo work"
    )


def test_force_name_reuse_leaves_bare_and_missing_name_directives() -> None:
    assert _force_name_reuse_in_prompt("%id\nDo work") == "%id\nDo work"
    assert _force_name_reuse_in_prompt("Do work") == "Do work"


def test_force_name_reuse_ignores_fenced_and_disabled_name_directives() -> None:
    prompt = (
        "```\n%id:fenced\n```\n"
        "%xprompts_enabled:false\n"
        "%i:disabled\n"
        "%xprompts_enabled:true\n"
        "Do work"
    )
    assert _force_name_reuse_in_prompt(prompt) == prompt


@pytest.mark.parametrize(
    ("raw_prompt", "agent_name", "expected"),
    [
        ("%i:foo\nDo work", "foo", "%i:!foo\nDo work"),
        ("%id:foo\nDo work", "foo", "%id:!foo\nDo work"),
        ("%id:@.cld\nDo work", "0.cld", "%id:!0.cld\nDo work"),
        ("%id:!foo\nDo work", "foo", "%id:!foo\nDo work"),
        ("Do work", None, "Do work"),
    ],
)
def test_prepare_kill_and_edit_prompt_contract(
    raw_prompt: str,
    agent_name: str | None,
    expected: str,
) -> None:
    assert prepare_kill_and_edit_prompt(raw_prompt, agent_name) == expected


@patch("sase.agent.names.allocate_retry_name", return_value="foo.r0")
def test_retry_edit_agent_prepends_allocated_retry_name(
    _mock_allocate: Mock,
) -> None:
    app = _App(_Agent("Do work", agent_name="foo"))

    app._retry_edit_agent()

    assert app.launched == (
        "%id:foo.r0\nDo work",
        "/tmp/proj/proj.sase",
        "branch",
        False,
    )
    assert app.notifications == []


@patch("sase.agent.names.allocate_retry_name", return_value="foo.r0")
def test_retry_edit_agent_preserves_unnamed_agent_prompt(
    mock_allocate: Mock,
) -> None:
    app = _App(_Agent("Do work", agent_name=None))

    app._retry_edit_agent()

    assert app.launched == ("Do work", "/tmp/proj/proj.sase", "branch", False)
    assert app.notifications == []
    assert not mock_allocate.called


@patch("sase.agent.names.allocate_retry_name", return_value="foo.r0")
def test_retry_edit_agent_replaces_name_without_force_reuse(
    _mock_allocate: Mock,
) -> None:
    app = _App(_Agent("%id:foo\nDo work", agent_name="foo"))

    app._retry_edit_agent()

    assert app.launched == (
        "%id:foo.r0\nDo work",
        "/tmp/proj/proj.sase",
        "branch",
        False,
    )
    assert app.notifications == []


@patch("sase.agent.names.allocate_retry_name", return_value="root.worker.r0")
def test_retry_edit_agent_demotes_clan_declaration(
    _mock_allocate: Mock,
) -> None:
    app = _App(
        _Agent(
            "%id:root.worker\n%clan(root, tribe=review)\nDo work",
            agent_name="root.worker",
        )
    )

    app._retry_edit_agent()

    assert app.launched == (
        "%id(worker.r0, clan=root)\nDo work",
        "/tmp/proj/proj.sase",
        "branch",
        False,
    )


def test_kill_and_edit_agent_demotes_clan_declaration() -> None:
    app = _App(
        _Agent(
            "%id:root.worker\n%clan(root, tribe=review)\nDo work",
            agent_name="root.worker",
        )
    )

    app._kill_and_edit_agent()

    assert app.launched == (
        "%id(!worker, clan=root)\nDo work",
        "/tmp/proj/proj.sase",
        "branch",
        False,
    )


def test_kill_and_edit_agent_forces_name_reuse_for_done_agent() -> None:
    app = _App(_Agent("%i:foo\nDo work", agent_name="foo"))

    app._kill_and_edit_agent()

    assert app.launched == (
        "%i:!foo\nDo work",
        "/tmp/proj/proj.sase",
        "branch",
        False,
    )
    assert app.notifications == []


def test_kill_and_edit_agent_replaces_template_with_concrete_name() -> None:
    app = _App(_Agent("%id:@.cld\nDo work", agent_name="0.cld"))

    app._kill_and_edit_agent()

    assert app.launched == (
        "%id:!0.cld\nDo work",
        "/tmp/proj/proj.sase",
        "branch",
        False,
    )
    assert app.notifications == []
