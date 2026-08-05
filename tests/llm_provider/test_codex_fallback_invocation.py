"""Codex coverage for the shared commit finalizer path."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider._invoke import invoke_agent
from sase.llm_provider.codex import CodexProvider
from sase.llm_provider.types import LLMInvocationError


def _codex_popen_call_count(mock_popen: MagicMock) -> int:
    return sum(
        1
        for call in mock_popen.call_args_list
        if call.args and call.args[0] and Path(call.args[0][0]).name == "codex"
    )


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.provider_timer")
def test_codex_finalizer_runs_from_invoke_agent_when_dirty(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dirty worktree triggers a provider-neutral follow-up Codex turn."""
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "260511_130000")
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(tmp_path))
    dirty = (
        True,
        ["src/foo.py"],
        "commit",
        "Uncommitted changes detected:\nsrc/foo.py\n\ncommit using /sase_git_commit",
    )
    clean = (False, [], "", "")
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer.build_commit_details",
        MagicMock(side_effect=[dirty, clean]),
    )

    mock_popen.return_value = MagicMock()
    mock_stream.side_effect = [("primary-response", "", 0), ("final-response", "", 0)]
    provider = CodexProvider()

    with (
        patch("sase.llm_provider._invoke.get_provider", return_value=provider),
        patch("sase.llm_provider._invoke.postprocess_success"),
    ):
        result = invoke_agent(
            "primary-prompt",
            agent_type="test",
            provider_name="codex",
            suppress_output=True,
            skip_preprocessing=True,
            artifacts_dir=str(artifacts_dir),
        )

    assert _codex_popen_call_count(mock_popen) == 2
    second_call_stdin = mock_popen.return_value.stdin.write.call_args_list[-1].args[0]
    assert "src/foo.py" in second_call_stdin
    assert "/sase_git_commit" in second_call_stdin
    assert "--- Prior, Already-Terminated Output" in second_call_stdin
    assert "--- Commit Finalizer Pass 1 of 2 ---" in second_call_stdin
    assert result.content == "primary-response\n\nfinal-response"
    assert (artifacts_dir / "commit_finalizer_pass_1_prompt.md").exists()
    assert (artifacts_dir / "commit_finalizer_pass_1_response.md").exists()
    assert '"status": "finalized"' in (
        artifacts_dir / "commit_finalizer_result.json"
    ).read_text(encoding="utf-8")


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.provider_timer")
def test_codex_provider_invoke_no_longer_runs_private_fallback(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shared invoke layer, not CodexProvider.invoke(), owns finalization."""
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "260511_140000")
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    provider = CodexProvider()
    result = provider.invoke("test", model_tier="large", suppress_output=True)

    assert mock_popen.call_count == 1
    assert result.content == "response"


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.provider_timer")
def test_codex_finalizer_includes_bead_close_when_bead_id_set(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bead-close instruction still propagates through the shared helper."""
    from sase.commit_instructions import build_commit_instruction_message

    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "260511_170000")
    monkeypatch.setenv("SASE_BEAD_ID", "sase-31.2")
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(tmp_path))
    instr = build_commit_instruction_message(
        "/sase_git_commit", "create_commit", "sase-31.2"
    )
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer.build_commit_details",
        MagicMock(
            side_effect=[
                (
                    True,
                    ["src/foo.py"],
                    instr,
                    "Uncommitted changes detected:\n" + instr,
                ),
                (False, [], "", ""),
            ]
        ),
    )

    mock_popen.return_value = MagicMock()
    mock_stream.side_effect = [("primary", "", 0), ("final", "", 0)]
    provider = CodexProvider()

    with (
        patch("sase.llm_provider._invoke.get_provider", return_value=provider),
        patch("sase.llm_provider._invoke.postprocess_success"),
    ):
        invoke_agent(
            "test",
            agent_type="test",
            provider_name="codex",
            suppress_output=True,
            skip_preprocessing=True,
            artifacts_dir=str(artifacts_dir),
        )

    second_call_stdin = mock_popen.return_value.stdin.write.call_args_list[-1].args[0]
    assert "sase bead close sase-31.2" in second_call_stdin


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.provider_timer")
def test_codex_finalizer_fails_when_max_passes_stay_dirty(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The common finalizer fails the run instead of silently passing dirty work."""
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "260511_180000")
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer.build_commit_details",
        MagicMock(
            return_value=(True, ["a.py"], "commit", "Uncommitted changes detected")
        ),
    )
    mock_popen.return_value = MagicMock()
    mock_stream.side_effect = [("primary", "", 0), ("pass1", "", 0), ("pass2", "", 0)]
    provider = CodexProvider()

    with (
        patch("sase.llm_provider._invoke.get_provider", return_value=provider),
        patch("sase.llm_provider._invoke.postprocess_error"),
        pytest.raises(LLMInvocationError, match="Commit finalizer failed"),
    ):
        invoke_agent(
            "test",
            agent_type="test",
            provider_name="codex",
            suppress_output=True,
            skip_preprocessing=True,
            artifacts_dir=str(artifacts_dir),
        )

    assert _codex_popen_call_count(mock_popen) == 3
    assert '"status": "failed"' in (
        artifacts_dir / "commit_finalizer_result.json"
    ).read_text(encoding="utf-8")
