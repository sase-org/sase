"""Authorized ``sase run`` consumption side of the forced-reuse launch seam.

Split from ``tests.test_force_reuse_launch_seam``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import pytest

from sase.agent.force_reuse_bead import SASE_AGENT_FORCE_REUSE_BEAD_ENV
from sase.bead.work import SASE_BEAD_ID_ENV

from tests._force_reuse_launch_seam_helpers import (
    agent_session_kill_and_edit_prompt,
    clan_kill_and_edit_prompt,
    run_authorized_launch_query,
    submit_kill_and_edit,
)

__all__ = [
    "test_launch_query_consumes_authorized_agent_session_form",
    "test_launch_query_consumes_authorized_payload_and_wipes_reserved_name",
    "test_launch_query_fanout_contradiction_surfaces_clear_error",
    "test_launch_query_parse_failure_records_and_emits",
    "test_launch_query_threads_multi_prompt_segment_envs",
    "test_launch_query_wipe_failure_records_and_emits",
    "test_prepared_kill_and_edit_prompt_survives_submit_then_launch_query",
]


def test_launch_query_consumes_authorized_payload_and_wipes_reserved_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt = clan_kill_and_edit_prompt()

    wipe_names, mock_launch, record_failed, _emit, _exc = run_authorized_launch_query(
        prompt, monkeypatch
    )

    wipe_names.assert_called_once_with(["sase-op.2"])
    record_failed.assert_not_called()
    mock_launch.assert_called_once()
    args, kwargs = mock_launch.call_args
    assert args[0] == (
        "%id(2, clan=sase-op, bead=sase-op.2)\n#gh:gh_sase-org__sase\nDo work"
    )
    segment_envs = kwargs["segment_extra_env"]
    assert segment_envs is not None
    assert segment_envs[0] is not None
    assert segment_envs[0][SASE_AGENT_FORCE_REUSE_BEAD_ENV] == (
        '{"bead_id":"sase-op.2","owner_name":"sase-op.2"}'
    )
    assert segment_envs[0][SASE_BEAD_ID_ENV] == "sase-op.2"


def test_launch_query_consumes_authorized_agent_session_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt = agent_session_kill_and_edit_prompt()

    wipe_names, mock_launch, _record_failed, _emit, _exc = run_authorized_launch_query(
        prompt, monkeypatch
    )

    wipe_names.assert_called_once_with(["sase-oc.4--plan"])
    mock_launch.assert_called_once()
    args, kwargs = mock_launch.call_args
    assert args[0] == "%id(plan, session=sase-oc.4, bead=sase-oc.4)\nDo work"
    segment_envs = kwargs["segment_extra_env"]
    assert segment_envs is not None
    assert segment_envs[0] is not None
    assert segment_envs[0][SASE_AGENT_FORCE_REUSE_BEAD_ENV] == (
        '{"bead_id":"sase-oc.4","owner_name":"sase-oc.4--plan"}'
    )
    assert segment_envs[0][SASE_BEAD_ID_ENV] == "sase-oc.4"


def test_launch_query_threads_multi_prompt_segment_envs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt = (
        "%id(!a, bead=sase-1)\nFirst\n---\n"
        "%id:ordinary\nSecond\n---\n"
        "%i(!b, clan=crew, bead=sase-2)\nThird"
    )

    wipe_names, mock_launch, _record_failed, _emit, _exc = run_authorized_launch_query(
        prompt, monkeypatch
    )

    wipe_names.assert_called_once_with(["a", "crew.b"])
    args, kwargs = mock_launch.call_args
    assert args[0] == (
        "%id(a, bead=sase-1)\nFirst\n---\n"
        "%id:ordinary\nSecond\n---\n"
        "%i(b, clan=crew, bead=sase-2)\nThird"
    )
    segment_envs = kwargs["segment_extra_env"]
    assert segment_envs is not None
    assert len(segment_envs) == 3
    assert segment_envs[0] is not None
    assert segment_envs[0][SASE_AGENT_FORCE_REUSE_BEAD_ENV] == (
        '{"bead_id":"sase-1","owner_name":"a"}'
    )
    assert segment_envs[0][SASE_BEAD_ID_ENV] == "sase-1"
    assert segment_envs[1] is None
    assert segment_envs[2] is not None
    assert segment_envs[2][SASE_AGENT_FORCE_REUSE_BEAD_ENV] == (
        '{"bead_id":"sase-2","owner_name":"crew.b"}'
    )
    assert segment_envs[2][SASE_BEAD_ID_ENV] == "sase-2"


def test_prepared_kill_and_edit_prompt_survives_submit_then_launch_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ACE ``,x`` producer, durable payload, and child consumer agree."""
    prompt = clan_kill_and_edit_prompt()
    call = submit_kill_and_edit(prompt)
    assert call["request"]["allow_force_reuse"] is True
    assert call["request"]["prompt"] == prompt

    wipe_names, mock_launch, _record_failed, _emit, _exc = run_authorized_launch_query(
        call["request"]["prompt"], monkeypatch
    )

    wipe_names.assert_called_once_with(["sase-op.2"])
    mock_launch.assert_called_once()
    assert mock_launch.call_args.args[0] == (
        "%id(2, clan=sase-op, bead=sase-op.2)\n#gh:gh_sase-org__sase\nDo work"
    )


def test_launch_query_fanout_contradiction_surfaces_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt = "%id(!2, clan=sase-op)\n%{%m:claude/opus | %m:claude/sonnet}"

    wipe_names, mock_launch, record_failed, emit_result, exc = (
        run_authorized_launch_query(prompt, monkeypatch, expect_launch=False)
    )

    assert exc.code == 1
    wipe_names.assert_not_called()
    mock_launch.assert_not_called()
    record_failed.assert_called_once_with(prompt, origin="typed")
    emit_result.assert_called_once()
    emit_kwargs = emit_result.call_args.kwargs
    assert emit_kwargs["success"] is False
    assert "cannot be combined" in emit_kwargs["message"]


def test_launch_query_wipe_failure_records_and_emits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt = "%id:!foo\nDo work"

    wipe_names, mock_launch, record_failed, emit_result, exc = (
        run_authorized_launch_query(
            prompt,
            monkeypatch,
            wipe_side_effect=RuntimeError("boom"),
            expect_launch=False,
        )
    )

    assert exc.code == 1
    wipe_names.assert_called_once_with(["foo"])
    mock_launch.assert_not_called()
    record_failed.assert_called_once_with(prompt, origin="typed")
    emit_result.assert_called_once()
    emit_kwargs = emit_result.call_args.kwargs
    assert emit_kwargs["success"] is False
    assert emit_kwargs["message"] == "Agent name reuse failed: boom"


def test_launch_query_parse_failure_records_and_emits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt = (
        "---\nxprompts:\n  badname: content\n---\n"
        "%id:!foo\nFirst\n---\n%id:!bar\nSecond"
    )

    wipe_names, mock_launch, record_failed, emit_result, exc = (
        run_authorized_launch_query(prompt, monkeypatch, expect_launch=False)
    )

    assert exc.code == 1
    wipe_names.assert_not_called()
    mock_launch.assert_not_called()
    record_failed.assert_called_once_with(prompt, origin="typed")
    emit_result.assert_called_once()
    assert emit_result.call_args.kwargs["success"] is False
    assert "must start with '_'" in emit_result.call_args.kwargs["message"]
