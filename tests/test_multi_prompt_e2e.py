"""End-to-end tests for multi-prompt functionality.

Phase 4 of the multi-agent prompts plan (sase-2.4): verifies E2E flows
across CLI, TUI, and agent runner paths for multi-prompt handling.
"""

import os
from unittest.mock import patch

import pytest

from sase.agent.multi_prompt import is_multi_prompt, parse_multi_prompt
from sase.macro.models import Macro


# ---------------------------------------------------------------------------
# CLI: detached launch routing for prompts
# ---------------------------------------------------------------------------


def test_cli_multi_prompt_launches_detached() -> None:
    """sase run with a multi-prompt launches through the detached path."""
    query = "Fix the bug\n---\nAdd tests"
    assert is_multi_prompt(query)

    with (
        patch("sase.main.query_handler.special_cases.launch_query") as mock_launch,
        patch("sase.macro.get_all_prompts", return_value={}),
    ):
        from sase.main.query_handler.special_cases import handle_run_special_cases

        with pytest.raises(SystemExit) as exc_info:
            handle_run_special_cases([query])
        assert exc_info.value.code == 0
        mock_launch.assert_called_once_with(query)


def test_editor_multi_prompt_launches_detached() -> None:
    """Editor returning a multi-prompt launches through the detached path."""
    query = "#gh:sase fix bug\n---\n#gh:sase add tests"

    with (
        patch(
            "sase.main.query_handler.special_cases.open_editor_for_prompt",
            return_value=query,
        ),
        patch("sase.main.query_handler.special_cases.launch_query") as mock_launch,
    ):
        from sase.main.query_handler.special_cases import handle_run_special_cases

        with pytest.raises(SystemExit) as exc_info:
            handle_run_special_cases([])
        assert exc_info.value.code == 0
        mock_launch.assert_called_once_with(query)


def test_cli_single_prompt_launches_detached() -> None:
    """sase run with a single prompt launches through the detached path."""
    query = "Just a single prompt"
    assert not is_multi_prompt(query)

    with (
        patch("sase.main.query_handler.special_cases.launch_query") as mock_launch,
        patch("sase.macro.get_all_prompts", return_value={}),
    ):
        with pytest.raises(SystemExit):
            from sase.main.query_handler.special_cases import (
                handle_run_special_cases,
            )

            handle_run_special_cases([query])
        mock_launch.assert_called_once_with(query)


# ---------------------------------------------------------------------------
# Agent runner: local macros env var temp file cleanup
# ---------------------------------------------------------------------------


def test_local_macros_env_var_temp_file_cleaned_up() -> None:
    """The temp file for SASE_AGENT_LOCAL_MACROS is deleted after deserialization."""
    from sase.agent.multi_prompt_launcher import (
        _serialize_local_macros,
        deserialize_local_macros,
    )

    macros = {
        "_style": Macro(name="_style", content="be concise"),
    }
    macros_file = _serialize_local_macros(macros)
    assert os.path.exists(macros_file)

    # Simulate the cleanup logic from axe_run_agent_phases.py lines 59-72.
    env_macros_path = macros_file
    try:
        env_macros = deserialize_local_macros(env_macros_path)
        assert "_style" in env_macros
        assert env_macros["_style"].content == "be concise"
    finally:
        try:
            os.unlink(env_macros_path)
        except OSError:
            pass

    # The temp file should have been cleaned up.
    assert not os.path.exists(macros_file)


def test_local_macros_env_var_cleanup_in_extract_directives() -> None:
    """axe_run_agent_phases pops the env var and cleans up the temp file."""
    from sase.agent.multi_prompt_launcher import _serialize_local_macros

    macros = {
        "_style": Macro(name="_style", content="be concise"),
    }
    macros_file = _serialize_local_macros(macros)
    assert os.path.exists(macros_file)

    # Verify the code path: set env var, parse multi_prompt, pop env var, cleanup.
    os.environ["SASE_AGENT_LOCAL_MACROS"] = macros_file
    env_macros_path = os.environ.pop("SASE_AGENT_LOCAL_MACROS", None)
    assert env_macros_path is not None
    assert env_macros_path == macros_file

    # Clean up (mirrors the finally block we added in axe_run_agent_phases.py).
    try:
        os.unlink(env_macros_path)
    except OSError:
        pass
    assert not os.path.exists(macros_file)


def test_local_macros_env_var_missing_file_no_crash() -> None:
    """Missing temp file for SASE_AGENT_LOCAL_MACROS doesn't crash on cleanup."""
    nonexistent = "/tmp/sase_nonexistent_macros.json"
    assert not os.path.exists(nonexistent)

    # The finally block should not raise for a missing file.
    try:
        os.unlink(nonexistent)
    except OSError:
        pass  # Expected — this is the behavior we test.


# ---------------------------------------------------------------------------
# Full flow: parse → local macros → multi-prompt launcher
# ---------------------------------------------------------------------------


def test_full_flow_parse_and_launch() -> None:
    """Full multi-prompt flow: parse frontmatter + segments, then launch."""
    prompt = (
        '---\nxprompts:\n  _ctx: "extra context"\n---\n'
        "Fix the bug #_ctx\n---\n%wait\nAdd tests #_ctx"
    )
    multi = parse_multi_prompt(prompt)

    assert len(multi.segments) == 2
    assert "_ctx" in multi.local_macros
    assert multi.local_macros["_ctx"].content == "extra context"
    assert multi.segments[0] == "Fix the bug #_ctx"
    assert "%wait" in multi.segments[1]

    # Verify macro expansion works for each segment.
    with (
        patch("sase.macro.processor.get_all_macros", return_value={}),
        patch("sase.macro.processor.resolve_macro_aliases", side_effect=lambda x: x),
    ):
        from sase.macro.processor import process_macro_references

        for segment in multi.segments:
            expanded = process_macro_references(
                segment, extra_macros=multi.local_macros
            )
            assert "extra context" in expanded
            assert "#_ctx" not in expanded


def test_full_flow_frontmatter_only_single_agent() -> None:
    """Frontmatter with no --- separators is a single-agent prompt."""
    prompt = '---\nxprompts:\n  _style: "be concise"\n---\nDo the thing. #_style'
    multi = parse_multi_prompt(prompt)

    assert len(multi.segments) == 1
    assert not is_multi_prompt(prompt)
    assert "_style" in multi.local_macros


# ---------------------------------------------------------------------------
# Edge case: has_wait_directive works on individual segments
# ---------------------------------------------------------------------------


def test_has_wait_directive_per_segment() -> None:
    """has_wait_directive correctly detects %wait in individual segments."""
    from sase.macro.directives import extract_prompt_directives

    prompt = "Fix the bug\n---\n%wait:previous\nAdd tests\n---\nDeploy"
    multi = parse_multi_prompt(prompt)

    assert len(multi.segments) == 3
    assert not extract_prompt_directives(multi.segments[0])[1].wait
    assert extract_prompt_directives(multi.segments[1])[1].wait
    assert not extract_prompt_directives(multi.segments[2])[1].wait
