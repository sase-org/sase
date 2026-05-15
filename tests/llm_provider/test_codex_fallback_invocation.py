"""Codex commit-stop fallback invocation tests."""

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider.codex import CodexProvider
from tests.llm_provider._codex_fallback_helpers import (
    SIBLING_HOOK,
    isolate_fallback_markers,
    set_sase_session,
)


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.gemini_timer")
def test_codex_fallback_runs_when_dirty_and_no_native_marker(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dirty worktree without native marker triggers one follow-up turn."""
    isolate_fallback_markers(monkeypatch, tmp_path)
    session_id = set_sase_session(monkeypatch, "260511_130000")
    details = (
        "Uncommitted changes detected:\n"
        "src/foo.py\n\n"
        "A post-completion hook has detected uncommitted changes. "
        "commit using /sase_git_commit"
    )
    monkeypatch.setattr(
        "sase.llm_provider.codex.build_commit_details",
        lambda project_dir: (True, ["src/foo.py"], "commit", details),
    )

    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("second-turn-response", "", 0)

    provider = CodexProvider()
    result = provider.invoke("primary-prompt", model_tier="large", suppress_output=True)

    assert mock_popen.call_count == 2
    second_call_stdin = mock_popen.return_value.stdin.write.call_args_list[-1].args[0]
    assert "src/foo.py" in second_call_stdin
    assert "/sase_git_commit" in second_call_stdin
    assert "--- Work So Far ---" in second_call_stdin
    assert "--- Commit Stop Hook ---" in second_call_stdin

    native_marker = (
        Path(os.environ["SASE_TMPDIR"]) / f"sase_commit_hook_done_{session_id}"
    )
    fallback_marker = (
        Path(os.environ["SASE_TMPDIR"])
        / f"sase_codex_commit_fallback_done_{session_id}"
    )
    assert native_marker.exists()
    assert fallback_marker.exists()
    assert "second-turn-response" in result.content


def test_codex_fallback_runs_when_sibling_hook_blocks_clean_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex exec fallback also surfaces dirty sibling repos."""
    isolate_fallback_markers(monkeypatch, tmp_path)
    session_id = set_sase_session(monkeypatch, "260513_220000")
    project_dir = tmp_path / "sase"
    tools_dir = project_dir / "tools"
    sibling_dir = tmp_path / "sase-telegram"
    tools_dir.mkdir(parents=True)
    sibling_dir.mkdir()
    (tools_dir / "sase_sibling_commit_stop_hook").symlink_to(SIBLING_HOOK)
    subprocess.run(["git", "init", "-q"], cwd=sibling_dir, check=True)
    (sibling_dir / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(project_dir))
    monkeypatch.setattr(
        "sase.llm_provider.codex.build_commit_details",
        lambda project_dir: (False, [], "", ""),
    )

    emitted: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        "sase.llm_provider.codex.jlog",
        lambda event, **kwargs: emitted.append((event, kwargs)),
    )

    prompts: list[str] = []
    provider = CodexProvider()

    def fake_run_subprocess(
        args: list[str], prompt: str, suppress_output: bool
    ) -> tuple[str, str, int]:
        prompts.append(prompt)
        return "sibling-follow-up", "", 0

    monkeypatch.setattr(provider, "_run_subprocess", fake_run_subprocess)

    result = provider._maybe_run_commit_fallback_turn(
        base_args=["codex"],
        original_prompt="prompt",
        accumulated_response="response",
        suppress_output=True,
    )

    assert result == "sibling-follow-up"
    assert len(prompts) == 1
    assert "../sase-telegram" in prompts[0]
    assert "/sase_git_commit" in prompts[0]
    fallback_marker = (
        Path(os.environ["SASE_TMPDIR"])
        / f"sase_codex_commit_fallback_done_{session_id}"
    )
    sibling_marker = (
        Path(os.environ["SASE_TMPDIR"]) / f"sase_sibling_hook_done_{session_id}"
    )
    assert fallback_marker.exists()
    assert sibling_marker.exists()
    assert emitted[-1][0] == "codex_fallback_block_emitted"
    assert emitted[-1][1]["sibling_blocked"] is True


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.gemini_timer")
def test_codex_fallback_runs_even_when_native_marker_present(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Final worktree state dictates fallback; native marker is informational."""
    isolate_fallback_markers(monkeypatch, tmp_path)
    session_id = set_sase_session(monkeypatch, "260511_140000")
    native_marker = (
        Path(os.environ["SASE_TMPDIR"]) / f"sase_commit_hook_done_{session_id}"
    )
    native_marker.touch()

    monkeypatch.setattr(
        "sase.llm_provider.codex.build_commit_details",
        lambda project_dir: (True, ["a.py"], "commit", "details body"),
    )

    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    provider = CodexProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    assert mock_popen.call_count == 2


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.gemini_timer")
def test_codex_fallback_skipped_when_fallback_marker_already_present(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One-shot: don't fire again once the fallback marker exists."""
    isolate_fallback_markers(monkeypatch, tmp_path)
    session_id = set_sase_session(monkeypatch, "260511_150000")
    fallback_marker = (
        Path(os.environ["SASE_TMPDIR"])
        / f"sase_codex_commit_fallback_done_{session_id}"
    )
    fallback_marker.touch()

    monkeypatch.setattr(
        "sase.llm_provider.codex.build_commit_details",
        lambda project_dir: (True, ["a.py"], "commit", "details"),
    )

    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    provider = CodexProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    assert mock_popen.call_count == 1


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.gemini_timer")
def test_codex_fallback_disabled_by_env(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SASE_DISABLE_COMMIT_STOP_HOOK=1 keeps the provider to a single invocation."""
    isolate_fallback_markers(monkeypatch, tmp_path)
    set_sase_session(monkeypatch, "260511_160000")
    monkeypatch.setenv("SASE_DISABLE_COMMIT_STOP_HOOK", "1")
    monkeypatch.setattr(
        "sase.llm_provider.codex.build_commit_details",
        lambda project_dir: (True, ["a.py"], "commit", "details"),
    )

    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    provider = CodexProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    assert mock_popen.call_count == 1


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.gemini_timer")
def test_codex_fallback_includes_bead_close_when_bead_id_set(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bead-close instruction propagates from the shared helper to the prompt."""
    isolate_fallback_markers(monkeypatch, tmp_path)
    set_sase_session(monkeypatch, "260511_170000")
    monkeypatch.setenv("SASE_BEAD_ID", "sase-31.2")

    captured: dict[str, str] = {}

    def fake_build(project_dir: str) -> tuple[bool, list[str], str, str]:
        from sase.scripts.sase_commit_stop_hook import (
            _build_commit_instruction_message,
        )

        instr = _build_commit_instruction_message(
            "/sase_git_commit", "create_commit", "sase-31.2"
        )
        details = "Uncommitted changes detected:\nsrc/foo.py\n\n" + instr
        captured["details"] = details
        return (True, ["src/foo.py"], instr, details)

    monkeypatch.setattr("sase.llm_provider.codex.build_commit_details", fake_build)

    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    provider = CodexProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    second_call_stdin = mock_popen.return_value.stdin.write.call_args_list[-1].args[0]
    assert "sase bead close sase-31.2" in second_call_stdin


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.gemini_timer")
def test_codex_fallback_is_one_shot_when_second_turn_leaves_dirty(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider returns after exactly two invocations even if still dirty."""
    isolate_fallback_markers(monkeypatch, tmp_path)
    set_sase_session(monkeypatch, "260511_180000")
    monkeypatch.setattr(
        "sase.llm_provider.codex.build_commit_details",
        lambda project_dir: (True, ["a.py"], "commit", "still dirty"),
    )

    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    provider = CodexProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    assert mock_popen.call_count == 2
