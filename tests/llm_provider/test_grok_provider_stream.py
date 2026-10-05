"""GrokProvider Messages stream fixture replays."""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import pytest

from sase.ace.tui.thinking.parser import read_codex_thinking
from sase.llm_provider.grok import GrokProvider

from ._grok_provider_core_helpers import clear_grok_env_vars

GROK_STREAM_FIXTURES = Path(__file__).parents[1] / "fixtures" / "grok_stream"
_NO_TOOL_FIXTURE = GROK_STREAM_FIXTURES / "grok_messages_notool_1.0.3.jsonl"
_TOOLS_FIXTURE = GROK_STREAM_FIXTURES / "grok_messages_tools_1.0.3.jsonl"
_ERROR_FIXTURE = GROK_STREAM_FIXTURES / "grok_messages_error_1.0.3.jsonl"


@pytest.fixture(autouse=True)
def _clear_grok_env(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_grok_env_vars(monkeypatch)


def _make_fake_grok(
    tmp_path: Path,
    fixture: Path,
    *,
    exit_code: int = 0,
    chunk_size: int = 0,
    expected_prompt: str = "fixture prompt",
) -> Path:
    path = tmp_path / "grok"
    path.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env python3
            import sys
            from pathlib import Path

            prompt = sys.stdin.read()
            if prompt != {expected_prompt!r}:
                sys.stderr.write(f"unexpected prompt: {{prompt!r}}\\n")
                sys.exit(64)

            payload = Path({str(fixture)!r}).read_text(encoding="utf-8")
            chunk_size = {chunk_size}
            if chunk_size:
                for index in range(0, len(payload), chunk_size):
                    sys.stdout.write(payload[index:index + chunk_size])
                    sys.stdout.flush()
            else:
                sys.stdout.write(payload)
                sys.stdout.flush()
            sys.exit({exit_code})
            """
        ),
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def test_grok_provider_replays_no_tool_fixture_and_accumulates_usage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_grok = _make_fake_grok(
        tmp_path,
        _NO_TOOL_FIXTURE,
        chunk_size=7,
    )
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_GROK_PATH", str(fake_grok))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))

    result = GrokProvider().invoke(
        "fixture prompt", model_tier="large", suppress_output=True
    )

    assert result.content == "Grok says hello."
    assert result.usage == {
        "input_tokens": 12,
        "output_tokens": 7,
        "cache_creation_input_tokens": 4,
        "cache_read_input_tokens": 3,
    }
    assert (artifacts / "live_reply.md").read_text(encoding="utf-8") == (
        "Grok says hello."
    )
    assert (
        json.loads((artifacts / "usage.json").read_text(encoding="utf-8"))[
            "cache_creation_input_tokens"
        ]
        == 4
    )
    blocks = read_codex_thinking(str(artifacts))
    assert blocks is not None
    assert [block.text for block in blocks] == ["Need answer directly."]


def test_grok_provider_replays_tool_fixture_and_writes_grok_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_grok = _make_fake_grok(tmp_path, _TOOLS_FIXTURE)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_GROK_PATH", str(fake_grok))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))

    result = GrokProvider().invoke(
        "fixture prompt", model_tier="large", suppress_output=True
    )

    assert result.content == "Created the file and counted it."
    records = [
        json.loads(line)
        for line in (artifacts / "tool_calls.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert [record["event"] for record in records] == [
        "ToolUse",
        "ToolResult",
        "ToolUse",
        "ToolResult",
    ]
    assert {record["runtime"] for record in records} == {"grok"}
    assert records[0]["tool_name"] == "Bash"
    assert records[0]["tool_input_summary"]["command"] == "wc -c hello.txt"
    assert records[1]["tool_response_summary"]["exit_code"] == 0
    assert records[2]["tool_name"] == "Edit"
    assert records[3]["tool_response_summary"]["file_path"] == (
        "/tmp/grok-fixture/hello.txt"
    )
    blocks = read_codex_thinking(str(artifacts))
    assert blocks is not None
    assert [block.text for block in blocks] == ["Summarize the completed tool work."]


def test_grok_provider_error_fixture_surfaces_errors_array(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_grok = _make_fake_grok(tmp_path, _ERROR_FIXTURE, exit_code=1)
    monkeypatch.setenv("SASE_GROK_PATH", str(fake_grok))

    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        GrokProvider().invoke(
            "fixture prompt", model_tier="large", suppress_output=True
        )

    assert excinfo.value.returncode == 1
    assert "[result] Couldn't set model 'definitely-not-a-model'" in (
        excinfo.value.stderr
    )
