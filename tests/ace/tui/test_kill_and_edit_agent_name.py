"""Tests for the Agents-tab kill-and-edit relaunch action."""

from __future__ import annotations

from ._retry_edit_agent_name_helpers import (
    _EPIC_ROOT_PROMPT,
    _EPIC_ROOT_RELAUNCH,
    _Agent,
    _App,
    _configured_machine_identity,
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
    app = _App(_Agent("%i:foo\nDo work", agent_name="athena.foo"))

    app._kill_and_edit_agent()

    assert app.launched == (
        "%id:!foo\nDo work",
        "/tmp/proj/proj.sase",
        "branch",
        False,
    )
    assert app.notifications == []


def test_kill_and_edit_family_phase_forces_exact_member_attachment() -> None:
    app = _App(
        _Agent(
            "%id:sase-8a.3\n%auto\nDo work",
            agent_name="athena.sase-8a.3--plan",
            agent_family="athena.sase-8a.3",
            role_suffix="--plan",
            phase_bead_id="sase-8a.3",
        )
    )

    app._kill_and_edit_agent()

    assert app.launched == (
        "%id(!plan, family=sase-8a.3, bead=sase-8a.3)\n%auto\nDo work",
        "/tmp/proj/proj.sase",
        "branch",
        False,
    )


def test_kill_and_edit_clan_member_preserves_hood() -> None:
    app = _App(
        _Agent(
            "%id(2, clan=sase-8k, bead=sase-8k.2)\nDo work",
            agent_name="athena.sase-8k.2",
        )
    )

    app._kill_and_edit_agent()

    assert app.launched == (
        "%id(!2, clan=sase-8k, bead=sase-8k.2)\nDo work",
        "/tmp/proj/proj.sase",
        "branch",
        False,
    )


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


def test_kill_and_edit_agent_keeps_prompt_when_it_has_no_id() -> None:
    app = _App(_Agent("#gh:gh_sase-org__sase Describe this repo.", agent_name="068"))

    app._kill_and_edit_agent()

    assert app.launched == (
        "#gh:gh_sase-org__sase Describe this repo.",
        "/tmp/proj/proj.sase",
        "branch",
        False,
    )
    assert app.notifications == []


def test_kill_and_edit_agent_blocks_non_restartable_archive() -> None:
    app = _App(
        _Agent(
            "%id:foo\nDo work",
            restartable=False,
            missing_requirements=("prompt", "model"),
        )
    )

    app._kill_and_edit_agent()

    assert app.launched is None
    assert app.notifications == [
        ("This archive record is not restartable: missing prompt, model", "warning")
    ]


def test_kill_and_edit_family_root_keeps_clan_identity() -> None:
    app = _App(
        _Agent(
            _EPIC_ROOT_PROMPT,
            agent_name="sase-pw.1--plan",
            agent_family="sase-pw.1",
            role_suffix="--plan",
            phase_bead_id="sase-pw.1",
            is_family_root_entry=True,
        )
    )

    app._kill_and_edit_agent()

    assert app.launched == (
        _EPIC_ROOT_RELAUNCH,
        "/tmp/proj/proj.sase",
        "branch",
        False,
    )
    assert app.notifications == []
