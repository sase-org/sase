"""ACE submission side of the forced-reuse launch seam.

Split from ``tests.test_force_reuse_launch_seam``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

from unittest.mock import patch

from sase.ops.names import RUN_LAUNCH

from tests._force_reuse_launch_seam_helpers import (
    SubmitHost,
    agent_session_kill_and_edit_prompt,
    clan_kill_and_edit_prompt,
    submit_kill_and_edit,
)

__all__ = [
    "test_kill_and_edit_submission_authorizes_forced_reuse_agent_session_form",
    "test_kill_and_edit_submission_authorizes_forced_reuse_clan_form",
    "test_marked_bulk_kill_and_edit_each_pane_authorizes_its_own_forced_name",
]


def test_kill_and_edit_submission_authorizes_forced_reuse_clan_form() -> None:
    """A clan-member ``,x`` relaunch prompt reaches the proc queue verbatim."""
    prompt = clan_kill_and_edit_prompt()

    call = submit_kill_and_edit(prompt)

    assert prompt == (
        "%id(!2, clan=sase-op, bead=sase-op.2)\n#gh:gh_sase-org__sase\nDo work"
    )
    assert call["operation"] == RUN_LAUNCH
    assert call["request"]["prompt"] == prompt
    assert call["request"]["allow_force_reuse"] is True


def test_kill_and_edit_submission_authorizes_forced_reuse_agent_session_form() -> None:
    """An agent-session ``,x`` relaunch prompt reaches the proc queue verbatim."""
    prompt = agent_session_kill_and_edit_prompt()

    call = submit_kill_and_edit(prompt)

    assert prompt == "%id(!plan, session=sase-oc.4, bead=sase-oc.4)\nDo work"
    assert call["request"]["prompt"] == prompt
    assert call["request"]["allow_force_reuse"] is True


def test_marked_bulk_kill_and_edit_each_pane_authorizes_its_own_forced_name() -> None:
    """Each pane of a marked/bulk ``,x`` submit gets its own authorized request."""
    host = SubmitHost()
    panes = [
        "%id(!1, clan=sase-op, bead=sase-op.1)\nFirst",
        "%id(!2, clan=sase-op, bead=sase-op.2)\nSecond",
    ]

    with patch(
        "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
        return_value=["forced-ts"],
    ):
        for pane in panes:
            host._launch_resolved_prompt(pane, keep_bar=True)

    assert len(host.calls) == 2
    for pane, call in zip(panes, host.calls, strict=True):
        assert call["request"]["prompt"] == pane
        assert call["request"]["allow_force_reuse"] is True
