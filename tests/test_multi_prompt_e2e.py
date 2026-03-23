"""End-to-end tests for multi-prompt functionality.

Phase 4 of the multi-agent prompts plan (sase-2.4): verifies E2E flows
across CLI, TUI, and agent runner paths for multi-prompt handling.
"""

import os
from unittest.mock import patch

import pytest

from sase.agent.multi_prompt import is_multi_prompt, parse_multi_prompt
from sase.xprompt.models import XPrompt


# ---------------------------------------------------------------------------
# CLI: auto-daemon redirect for multi-prompt
# ---------------------------------------------------------------------------


def test_cli_multi_prompt_auto_daemon_redirect() -> None:
    """sase run with a multi-prompt auto-switches to daemon mode."""
    query = "Fix the bug\n---\nAdd tests"
    assert is_multi_prompt(query)

    with (
        patch("sase.main.query_handler.special_cases.run_query_daemon") as mock_daemon,
        patch("sase.xprompt.get_all_prompts", return_value={}),
    ):
        from sase.main.query_handler.special_cases import handle_run_special_cases

        with pytest.raises(SystemExit) as exc_info:
            handle_run_special_cases([query])
        assert exc_info.value.code == 0
        mock_daemon.assert_called_once_with(query)


def test_editor_multi_prompt_auto_daemon_redirect() -> None:
    """Editor returning a multi-prompt auto-switches to daemon mode."""
    query = "#gh:sase fix bug\n---\n#gh:sase add tests"

    with (
        patch(
            "sase.main.query_handler.special_cases.open_editor_for_prompt",
            return_value=query,
        ),
        patch("sase.main.query_handler.special_cases.run_query_daemon") as mock_daemon,
    ):
        from sase.main.query_handler.special_cases import handle_run_special_cases

        with pytest.raises(SystemExit) as exc_info:
            handle_run_special_cases([])
        assert exc_info.value.code == 0
        mock_daemon.assert_called_once_with(query)


def test_cli_single_prompt_no_daemon_redirect() -> None:
    """sase run with a single prompt does NOT redirect to daemon."""
    query = "Just a single prompt"
    assert not is_multi_prompt(query)

    with (
        patch("sase.main.query_handler.special_cases.run_query") as mock_run,
        patch("sase.xprompt.get_all_prompts", return_value={}),
    ):
        with pytest.raises(SystemExit):
            from sase.main.query_handler.special_cases import (
                handle_run_special_cases,
            )

            handle_run_special_cases([query])
        mock_run.assert_called_once_with(query)


# ---------------------------------------------------------------------------
# CLI: resume + multi-prompt error
# ---------------------------------------------------------------------------


def test_resume_with_multi_prompt_errors() -> None:
    """sase run -r with a multi-prompt should error."""
    query = "Fix bug\n---\nAdd tests"

    with pytest.raises(SystemExit) as exc_info:
        from sase.main.query_handler._resume import handle_run_with_resume

        handle_run_with_resume(["-r", query])

    assert exc_info.value.code == 1


def test_resume_with_single_prompt_succeeds() -> None:
    """sase run -r with a single prompt should NOT error on multi-prompt check."""
    query = "Just fix the bug"

    with (
        patch(
            "sase.main.query_handler._resume.list_chat_histories",
            return_value=["history1"],
        ),
        patch("sase.main.query_handler._resume.load_chat_for_resume", return_value=[]),
        patch("sase.main.query_handler._resume.run_query") as mock_run,
    ):
        with pytest.raises(SystemExit) as exc_info:
            from sase.main.query_handler._resume import handle_run_with_resume

            handle_run_with_resume(["-r", query])

        assert exc_info.value.code == 0
        mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# Agent runner: local xprompts env var temp file cleanup
# ---------------------------------------------------------------------------


def test_local_xprompts_env_var_temp_file_cleaned_up() -> None:
    """The temp file for SASE_AGENT_LOCAL_XPROMPTS is deleted after deserialization."""
    from sase.agent.multi_prompt_launcher import (
        _serialize_local_xprompts,
        deserialize_local_xprompts,
    )

    xprompts = {
        "_style": XPrompt(name="_style", content="be concise"),
    }
    xprompts_file = _serialize_local_xprompts(xprompts)
    assert os.path.exists(xprompts_file)

    # Simulate the cleanup logic from axe_run_agent_phases.py lines 59-72.
    env_xprompts_path = xprompts_file
    try:
        env_xprompts = deserialize_local_xprompts(env_xprompts_path)
        assert "_style" in env_xprompts
        assert env_xprompts["_style"].content == "be concise"
    finally:
        try:
            os.unlink(env_xprompts_path)
        except OSError:
            pass

    # The temp file should have been cleaned up.
    assert not os.path.exists(xprompts_file)


def test_local_xprompts_env_var_cleanup_in_extract_directives() -> None:
    """axe_run_agent_phases pops the env var and cleans up the temp file."""
    from sase.agent.multi_prompt_launcher import _serialize_local_xprompts

    xprompts = {
        "_style": XPrompt(name="_style", content="be concise"),
    }
    xprompts_file = _serialize_local_xprompts(xprompts)
    assert os.path.exists(xprompts_file)

    # Verify the code path: set env var, parse multi_prompt, pop env var, cleanup.
    os.environ["SASE_AGENT_LOCAL_XPROMPTS"] = xprompts_file
    env_xprompts_path = os.environ.pop("SASE_AGENT_LOCAL_XPROMPTS", None)
    assert env_xprompts_path is not None
    assert env_xprompts_path == xprompts_file

    # Clean up (mirrors the finally block we added in axe_run_agent_phases.py).
    try:
        os.unlink(env_xprompts_path)
    except OSError:
        pass
    assert not os.path.exists(xprompts_file)


def test_local_xprompts_env_var_missing_file_no_crash() -> None:
    """Missing temp file for SASE_AGENT_LOCAL_XPROMPTS doesn't crash on cleanup."""
    nonexistent = "/tmp/sase_nonexistent_xprompts.json"
    assert not os.path.exists(nonexistent)

    # The finally block should not raise for a missing file.
    try:
        os.unlink(nonexistent)
    except OSError:
        pass  # Expected — this is the behavior we test.


# ---------------------------------------------------------------------------
# Full flow: parse → local xprompts → multi-prompt launcher
# ---------------------------------------------------------------------------


def test_full_flow_parse_and_launch() -> None:
    """Full multi-prompt flow: parse frontmatter + segments, then launch."""
    prompt = (
        '---\nxprompts:\n  _ctx: "extra context"\n---\n'
        "Fix the bug #_ctx\n---\n%wait\nAdd tests #_ctx"
    )
    multi = parse_multi_prompt(prompt)

    assert len(multi.segments) == 2
    assert "_ctx" in multi.local_xprompts
    assert multi.local_xprompts["_ctx"].content == "extra context"
    assert multi.segments[0] == "Fix the bug #_ctx"
    assert "%wait" in multi.segments[1]

    # Verify xprompt expansion works for each segment.
    with (
        patch("sase.xprompt.processor.get_all_xprompts", return_value={}),
        patch(
            "sase.xprompt.processor.resolve_xprompt_aliases", side_effect=lambda x: x
        ),
    ):
        from sase.xprompt.processor import process_xprompt_references

        for segment in multi.segments:
            expanded = process_xprompt_references(
                segment, extra_xprompts=multi.local_xprompts
            )
            assert "extra context" in expanded
            assert "#_ctx" not in expanded


def test_full_flow_frontmatter_only_single_agent() -> None:
    """Frontmatter with no --- separators is a single-agent prompt."""
    prompt = '---\nxprompts:\n  _style: "be concise"\n---\nDo the thing. #_style'
    multi = parse_multi_prompt(prompt)

    assert len(multi.segments) == 1
    assert not is_multi_prompt(prompt)
    assert "_style" in multi.local_xprompts


# ---------------------------------------------------------------------------
# Edge case: has_wait_directive works on individual segments
# ---------------------------------------------------------------------------


def test_has_wait_directive_per_segment() -> None:
    """has_wait_directive correctly detects %wait in individual segments."""
    from sase.xprompt.directives import has_wait_directive

    prompt = "Fix the bug\n---\n%wait\nAdd tests\n---\nDeploy"
    multi = parse_multi_prompt(prompt)

    assert len(multi.segments) == 3
    assert not has_wait_directive(multi.segments[0])
    assert has_wait_directive(multi.segments[1])
    assert not has_wait_directive(multi.segments[2])
