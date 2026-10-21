"""GrokProvider Messages stream fixture replays."""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch
from urllib.parse import quote

import pytest

from sase.ace.tui.thinking.parser import read_codex_thinking
from sase.llm_provider._grok_subprocess import (
    _GrokTurnEndProbe,
    _final_assistant_from_chat_history,
    _recover_grok_final_reply,
    _resolve_grok_session_dir,
)
from sase.llm_provider.grok import GrokProvider
from sase.llm_provider._subprocess_plain import ProviderTurnState
from sase.llm_provider._subprocess_reap import TeardownStall, register_teardown_stall

from ._grok_provider_core_helpers import clear_grok_env_vars, invoke_and_capture

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


_SESSION_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_CWD = "/work/tree"


def _session_dir(home: Path, cwd: str = _CWD, session_id: str = _SESSION_ID) -> Path:
    path = home / "sessions" / quote(cwd, safe="") / session_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_grok_session_dir_prefers_the_quoted_cwd_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GROK_HOME", str(tmp_path))
    exact = _session_dir(tmp_path)
    alt = tmp_path / "sessions" / "other-encoding" / _SESSION_ID
    alt.mkdir(parents=True)

    assert _resolve_grok_session_dir(_CWD, _SESSION_ID) == exact


def test_grok_session_dir_falls_back_to_globbing_the_session_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GROK_HOME", str(tmp_path))
    fallback = tmp_path / "sessions" / "other-encoding" / _SESSION_ID
    fallback.mkdir(parents=True)

    assert _resolve_grok_session_dir(_CWD, _SESSION_ID) == fallback


def test_grok_turn_end_probe_parses_incrementally_across_partial_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GROK_HOME", str(tmp_path))
    events = _session_dir(tmp_path) / "events.jsonl"
    events.write_bytes(b"")
    probe = _GrokTurnEndProbe(_CWD, _SESSION_ID)

    assert probe() is None

    events.write_bytes(b'{"type":"turn_started","turn_number":0}\n{"type":"turn_en')
    started = probe()
    assert started is not None
    assert started.phase == "started"

    with events.open("ab") as handle:
        handle.write(b'ded","outcome":"completed"}\n')
    ended = probe()
    assert ended == ProviderTurnState("ended", "completed")

    with events.open("ab") as handle:
        handle.write(b'{"type":"turn_started","turn_number":1}\n')
    restarted = probe()
    assert restarted == ProviderTurnState("started")


def test_grok_turn_end_probe_keeps_the_latest_of_multiple_turn_pairs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GROK_HOME", str(tmp_path))
    events = _session_dir(tmp_path) / "events.jsonl"
    events.write_text(
        '{"type":"turn_started"}\n'
        '{"type":"turn_ended","outcome":"cancelled"}\n'
        '{"type":"turn_started"}\n'
        '{"type":"turn_ended","outcome":"completed"}\n',
        encoding="utf-8",
    )

    assert _GrokTurnEndProbe(_CWD, _SESSION_ID)() == ProviderTurnState(
        "ended", "completed"
    )


def test_grok_starts_the_watchdog_with_a_turn_end_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_watchdog(*_args: object, **kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(
        "sase.llm_provider._grok_subprocess.start_completion_watchdog", fake_watchdog
    )
    invoke_and_capture(GrokProvider(), monkeypatch)

    assert captured["runtime"] == "grok"
    assert callable(captured.get("turn_end_probe"))


def test_grok_recovers_the_final_assistant_after_a_turn_end_reap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GROK_HOME", str(tmp_path))
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    (artifacts / "live_reply.md").write_text("intermediate narration", encoding="utf-8")
    session = _session_dir(tmp_path)
    (session / "chat_history.jsonl").write_text(
        json.dumps({"type": "assistant", "content": "", "tool_calls": [{}]})
        + "\n"
        + json.dumps({"type": "tool_result", "content": "ok"})
        + "\n"
        + json.dumps(
            {
                "type": "assistant",
                "content": "Newly added references now reset Bob Refs onto that row.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    process = MagicMock()
    stall = TeardownStall(
        runtime="grok",
        provider_pid=1,
        declared_at="2026-10-20T00:00:00+00:00",
        grace_seconds=120.0,
        trigger="provider_turn_end",
        turn_outcome="completed",
    )
    register_teardown_stall(cast(Any, process), stall)

    recovered = _recover_grok_final_reply(
        cast(Any, process),
        "intermediate narration",
        _CWD,
        _SESSION_ID,
    )

    assert recovered.endswith(
        "Newly added references now reset Bob Refs onto that row."
    )
    assert recovered.startswith("intermediate narration")
    assert "Newly added references" in (artifacts / "live_reply.md").read_text(
        encoding="utf-8"
    )


def test_grok_recovery_skips_a_final_assistant_already_in_the_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GROK_HOME", str(tmp_path))
    session = _session_dir(tmp_path)
    (session / "chat_history.jsonl").write_text(
        json.dumps({"type": "assistant", "content": "already streamed"}) + "\n",
        encoding="utf-8",
    )
    process = MagicMock()
    stall = TeardownStall(
        runtime="grok",
        provider_pid=1,
        declared_at="2026-10-20T00:00:00+00:00",
        grace_seconds=120.0,
        trigger="provider_turn_end",
        turn_outcome="completed",
    )
    register_teardown_stall(cast(Any, process), stall)

    assert (
        _recover_grok_final_reply(
            cast(Any, process), "prefix\n\nalready streamed", _CWD, _SESSION_ID
        )
        == "prefix\n\nalready streamed"
    )


def test_grok_recovery_tolerates_missing_and_garbled_chat_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GROK_HOME", str(tmp_path))
    process = MagicMock()
    stall = TeardownStall(
        runtime="grok",
        provider_pid=1,
        declared_at="2026-10-20T00:00:00+00:00",
        grace_seconds=120.0,
        trigger="provider_turn_end",
        turn_outcome="completed",
    )
    register_teardown_stall(cast(Any, process), stall)

    assert (
        _recover_grok_final_reply(cast(Any, process), "streamed", _CWD, _SESSION_ID)
        == "streamed"
    )

    session = _session_dir(tmp_path)
    (session / "chat_history.jsonl").write_text("{not json\n", encoding="utf-8")
    assert (
        _recover_grok_final_reply(cast(Any, process), "streamed", _CWD, _SESSION_ID)
        == "streamed"
    )
    assert _final_assistant_from_chat_history(session) is None
