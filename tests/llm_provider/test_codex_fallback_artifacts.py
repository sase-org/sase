"""Codex commit-stop fallback artifact tests."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider._invoke import invoke_agent
from sase.llm_provider._subprocess import stream_and_parse_codex_json_output
from sase.llm_provider.codex import CodexProvider
from tests.llm_provider._codex_fallback_helpers import (
    codex_tool_turn_events,
    isolate_fallback_markers,
    set_sase_session,
    start_fixture_codex_process,
)


def test_codex_finalizer_parser_cycle_appends_tool_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Commit finalizer turns append Codex tool rows to the same artifact."""
    isolate_fallback_markers(monkeypatch, tmp_path)
    set_sase_session(monkeypatch, "260511_130500")
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer.build_commit_details",
        MagicMock(
            side_effect=[
                (True, ["src/foo.py"], "commit", "details body"),
                (False, [], "", ""),
            ]
        ),
    )

    turns = [
        codex_tool_turn_events("primary_cmd", "primary reply"),
        codex_tool_turn_events("fallback_cmd", "fallback reply"),
    ]
    prompts: list[str] = []

    def fake_run_subprocess(
        args: list[str], prompt: str, suppress_output: bool
    ) -> tuple[str, str, int]:
        prompts.append(prompt)
        process = start_fixture_codex_process(turns[len(prompts) - 1])
        return stream_and_parse_codex_json_output(process, suppress_output=True)

    provider = CodexProvider()
    monkeypatch.setattr(provider, "_run_subprocess", fake_run_subprocess)

    with (
        patch("sase.llm_provider._invoke.get_provider", return_value=provider),
        patch("sase.llm_provider._invoke.postprocess_success"),
    ):
        result = invoke_agent(
            "primary prompt",
            agent_type="test",
            provider_name="codex",
            suppress_output=True,
            skip_preprocessing=True,
            artifacts_dir=str(artifacts_dir),
        )

    assert result.content == "primary reply\n\nfallback reply"
    assert len(prompts) == 2
    assert "--- Commit Finalizer Pass 1 of 2 ---" in prompts[1]

    records = [
        json.loads(line)
        for line in (artifacts_dir / "tool_calls.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [record["tool_use_id"] for record in records] == [
        "primary_cmd",
        "primary_cmd",
        "fallback_cmd",
        "fallback_cmd",
    ]
    assert [record["event"] for record in records] == [
        "ToolUse",
        "ToolResult",
        "ToolUse",
        "ToolResult",
    ]
    assert (artifacts_dir / "live_reply.md").read_text(encoding="utf-8") == (
        "primary reply\n\nfallback reply"
    )
