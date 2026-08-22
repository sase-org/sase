"""Codex commit-stop fallback artifact tests."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.llm_provider._invoke import invoke_agent
from sase.llm_provider._subprocess import stream_and_parse_codex_json_output
from sase.llm_provider.codex import CodexProvider
from tests.llm_provider._codex_fallback_helpers import (
    codex_tool_turn_events,
    init_dirty_project,
    isolate_fallback_markers,
    set_sase_session,
    start_fixture_codex_process,
    use_git_dirty_details,
)


def test_codex_primary_turn_appends_tool_artifacts_with_generic_finalizer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Codex primary turn still writes tool rows when generic finalizers run."""
    isolate_fallback_markers(monkeypatch, tmp_path)
    set_sase_session(monkeypatch, "260511_130500")
    project_dir = tmp_path / "project"
    init_dirty_project(project_dir)
    use_git_dirty_details(monkeypatch)
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    prompts: list[str] = []

    def fake_run_subprocess(
        args: list[str], prompt: str, suppress_output: bool
    ) -> tuple[str, str, int]:
        prompts.append(prompt)
        process = start_fixture_codex_process(
            codex_tool_turn_events("primary_cmd", "primary reply")
        )
        return stream_and_parse_codex_json_output(process, suppress_output=True)

    provider = CodexProvider()
    monkeypatch.setattr(provider, "_run_subprocess", fake_run_subprocess)

    with (
        patch("sase.llm_provider._invoke.get_provider", return_value=provider),
        patch("sase.llm_provider._invoke.postprocess_success"),
        patch(
            "sase.finalizers.run_finalizers",
            side_effect=lambda **kwargs: kwargs["invoke_result"],
        ),
    ):
        result = invoke_agent(
            "primary prompt",
            agent_type="test",
            provider_name="codex",
            suppress_output=True,
            skip_preprocessing=True,
            artifacts_dir=str(artifacts_dir),
        )

    assert result.content == "primary reply"
    assert len(prompts) == 1
    assert prompts[0] == "primary prompt"

    records = [
        json.loads(line)
        for line in (artifacts_dir / "tool_calls.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [record["tool_use_id"] for record in records] == [
        "primary_cmd",
        "primary_cmd",
    ]
    assert [record["event"] for record in records] == [
        "ToolUse",
        "ToolResult",
    ]
    assert (artifacts_dir / "live_reply.md").read_text(encoding="utf-8") == (
        "primary reply"
    )
