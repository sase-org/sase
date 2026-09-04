"""Tests for the Agents-tab retry-edit relaunch action."""

from __future__ import annotations

from unittest.mock import Mock, patch

from ._retry_edit_agent_name_helpers import (
    _Agent,
    _App,
    _configured_machine_identity,
)


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


@patch(
    "sase.agent.names.allocate_retry_name",
    return_value="athena.foo.r0",
)
def test_retry_edit_qualified_local_agent_uses_prompt_facing_name(
    mock_allocate: Mock,
) -> None:
    app = _App(_Agent("%id:foo\nDo work", agent_name="athena.foo"))

    app._retry_edit_agent()

    mock_allocate.assert_called_once_with("foo")
    assert app.launched == (
        "%id:foo.r0\nDo work",
        "/tmp/proj/proj.sase",
        "branch",
        False,
    )


@patch(
    "sase.agent.names.allocate_retry_name",
    return_value="athena.sase-8a.3.r0",
)
def test_retry_edit_qualified_local_family_phase_allocates_from_presented_base(
    mock_allocate: Mock,
) -> None:
    app = _App(
        _Agent(
            "%id:sase-8a.3\n%auto\nDo work",
            agent_name="athena.sase-8a.3--plan",
        )
    )

    app._retry_edit_agent()

    mock_allocate.assert_called_once_with("sase-8a.3")
    assert app.launched == (
        "%id:sase-8a.3.r0\n%auto\nDo work",
        "/tmp/proj/proj.sase",
        "branch",
        False,
    )


@patch(
    "sase.agent.names.allocate_retry_name",
    return_value="athena.sase-8k.2.r0",
)
def test_retry_edit_qualified_local_clan_member_preserves_clan_name(
    mock_allocate: Mock,
) -> None:
    app = _App(
        _Agent(
            "%id(2, clan=sase-8k, bead=sase-8k.2)\nDo work",
            agent_name="athena.sase-8k.2",
        )
    )

    app._retry_edit_agent()

    mock_allocate.assert_called_once_with("sase-8k.2")
    assert app.launched == (
        "%id(2.r0, clan=sase-8k, bead=sase-8k.2)\nDo work",
        "/tmp/proj/proj.sase",
        "branch",
        False,
    )


@patch("sase.agent.names.allocate_retry_name", return_value="foo.r0")
def test_retry_edit_agent_preserves_unnamed_agent_prompt(
    mock_allocate: Mock,
) -> None:
    app = _App(_Agent("Do work", agent_name=None))

    app._retry_edit_agent()

    assert app.launched == ("Do work", "/tmp/proj/proj.sase", "branch", False)
    assert app.notifications == []
    assert not mock_allocate.called


def test_retry_edit_agent_blocks_non_restartable_archive() -> None:
    app = _App(
        _Agent(
            "Do work",
            restartable=False,
            missing_requirements=("prompt",),
        )
    )

    app._retry_edit_agent()

    assert app.launched is None
    assert app.notifications == [
        ("This archive record is not restartable: missing prompt", "warning")
    ]


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


@patch("sase.agent.names.allocate_retry_name", return_value="root.worker.r0")
def test_retry_edit_agent_preserves_clan_joiner_membership(
    _mock_allocate: Mock,
) -> None:
    app = _App(
        _Agent(
            "%id(worker, clan=root)\nDo work",
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


@patch(
    "sase.agent.names.allocate_retry_name",
    return_value="research.2.worker.r0",
)
def test_retry_edit_agent_resolves_template_clan_membership(
    _mock_allocate: Mock,
) -> None:
    app = _App(
        _Agent(
            "%id:research.@.worker\n%clan(research.@, tribe=review)\nDo work",
            agent_name="research.2.worker",
        )
    )

    app._retry_edit_agent()

    assert app.launched == (
        "%id(worker.r0, clan=research.2)\nDo work",
        "/tmp/proj/proj.sase",
        "branch",
        False,
    )
