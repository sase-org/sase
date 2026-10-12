"""Tests for onboarding NDJSON event emit and parse."""

from __future__ import annotations

from io import StringIO

from sase.project_onboarding.events import emit_event, parse_event_line


class TestEvents:
    def test_emit_writes_one_ndjson_line(self) -> None:
        stream = StringIO()
        emit_event({"event": "plan", "plan": {"status": "ready"}}, file=stream)
        text = stream.getvalue()
        assert text.endswith("\n")
        assert text.count("\n") == 1
        parsed = parse_event_line(text)
        assert parsed is not None
        assert parsed["event"] == "plan"
        assert parsed["plan"]["status"] == "ready"

    def test_parse_step_and_result(self) -> None:
        step = parse_event_line(
            '{"event":"step","id":"checkout","status":"running","label":"Clone"}'
        )
        assert step is not None
        assert step["id"] == "checkout"
        result = parse_event_line(
            '{"event":"result","status":"ok","project_key":"bob","message":"ready"}'
        )
        assert result is not None
        assert result["status"] == "ok"

    def test_malformed_and_unknown_lines_are_none(self) -> None:
        assert parse_event_line("") is None
        assert parse_event_line("not-json") is None
        assert parse_event_line('{"event":"plan"}') is None
        assert parse_event_line('{"event":"unknown","id":"x"}') is None
        assert parse_event_line("[1, 2]") is None
        assert parse_event_line('{"event":"step","status":"running"}') is None
        assert parse_event_line('{"event":"result","status":"nope"}') is None

    def test_control_characters_are_stripped(self) -> None:
        parsed = parse_event_line(
            '{"event":"result","status":"ok","message":"hi\\u0007there"}'
        )
        assert parsed is not None
        assert parsed["message"] == "hithere"
