"""Claude subscription-usage collector and passive event tests."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pytest

from sase.llm_provider._subprocess_claude import _process_json_line
from sase.llm_provider.claude import ClaudeCodeProvider
from sase.llm_provider.usage.claude import (
    _claude_rate_limit_event_observation,
    capture_claude_passive_usage_context,
    collect_claude_usage,
)
from sase.llm_provider.usage._claude_support import (
    CLAUDE_USAGE_PROBE_BUDGET_USD,
    ClaudeCommandResult,
    parse_claude_reset_timestamp,
)
from sase.llm_provider.usage.probe import default_probe_context, run_usage_probe
from sase.llm_provider.usage.types import UsageProbeContext

OBSERVED_AT = datetime(
    2026,
    9,
    7,
    18,
    0,
    tzinfo=ZoneInfo("America/New_York"),
).timestamp()
_ZERO_BUDGET_ERROR = (
    "error: option '--max-budget-usd <amount>' argument '0' is invalid. "
    "--max-budget-usd must be a positive number greater than 0"
)


def _usage_tail(
    budget: str = CLAUDE_USAGE_PROBE_BUDGET_USD,
) -> tuple[str, ...]:
    return (
        "-p",
        "--output-format",
        "json",
        "--safe-mode",
        "--no-session-persistence",
        "--permission-prompts",
        "none",
        "--max-budget-usd",
        budget,
        "/usage",
    )


class FakeClaudeRunner:
    """Scripted command runner keyed by Claude argv tails."""

    def __init__(
        self,
        responses: Mapping[tuple[str, ...], ClaudeCommandResult],
    ) -> None:
        self.responses = dict(responses)
        self.calls: list[tuple[str, ...]] = []

    def __call__(
        self,
        argv: Sequence[str],
        cwd: str | None,
        deadline_at: float,
    ) -> ClaudeCommandResult:
        del cwd, deadline_at
        tail = tuple(argv[1:])
        self.calls.append(tail)
        if tail == _usage_tail("0"):
            return ClaudeCommandResult(1, "", _ZERO_BUDGET_ERROR)
        if tail not in self.responses:
            raise AssertionError(f"unexpected Claude command: {tail!r}")
        return self.responses[tail]


def _context() -> UsageProbeContext:
    return default_probe_context(
        "claude",
        now=OBSERVED_AT,
        executable="/fake/bin/claude",
        context_id="ctx",
        account_generation=2,
        operation_id="op",
    )


def _runner(
    *,
    usage_text: str = "",
    usage_payload: Mapping[str, object] | None = None,
    auth_payload: Mapping[str, object] | None = None,
    version: str = "2.1.263 (Claude Code)",
) -> FakeClaudeRunner:
    payload = usage_payload or {
        "type": "result",
        "result": usage_text,
        "total_cost_usd": 0,
        "num_turns": 0,
    }
    return FakeClaudeRunner(
        {
            ("--version",): ClaudeCommandResult(0, version, ""),
            ("-p", "--help"): ClaudeCommandResult(
                0,
                "--output-format json --max-budget-usd --safe-mode "
                "--no-session-persistence",
                "",
            ),
            ("auth", "status", "--help"): ClaudeCommandResult(0, "--json", ""),
            ("auth", "status", "--json"): ClaudeCommandResult(
                0,
                json.dumps(
                    auth_payload
                    or {
                        "authenticated": True,
                        "authType": "oauth",
                        "account": {"email": "private@example.com"},
                        "plan": "Max",
                    }
                ),
                "",
            ),
            _usage_tail(): ClaudeCommandResult(0, json.dumps(payload), ""),
        }
    )


def test_claude_usage_probe_parses_all_windows_and_one_cent_cap_argv() -> None:
    usage_text = "\n".join(
        [
            "You are currently using your Claude Max subscription.",
            "Current session: 10% used - resets Sep 7, 6:30pm (America/New_York)",
            "Current week: 25% used - resets Sep 12, 8pm (America/New_York)",
            "Current Fable weekly: 94% used - resets Sep 12, 2026, 8pm "
            "(America/New_York)",
        ]
    )
    runner = _runner(usage_text=usage_text)

    observation = collect_claude_usage(
        _context(),
        runner=runner,
        clock=lambda: OBSERVED_AT + 1.0,
    )

    assert observation["outcome"] == "ok"
    assert observation["completeness"] == "complete"
    assert observation["account_mode"] == "subscription"
    assert observation["plan"] == "Max"
    windows = {window["key"]: window for window in observation["windows"]}
    assert sorted(windows) == ["session", "weekly", "weekly:claude-fable-5"]
    assert windows["session"]["used_percent"] == 10.0
    assert (
        windows["session"]["resets_at"]
        == datetime(
            2026,
            9,
            7,
            18,
            30,
            tzinfo=ZoneInfo("America/New_York"),
        ).timestamp()
    )
    assert windows["weekly"]["applicability"] == {
        "kind": "product",
        "product": "claude",
        "model_ids": [],
    }
    assert windows["weekly:claude-fable-5"]["applicability"] == {
        "kind": "models",
        "model_ids": ["claude-fable-5"],
    }
    usage_call = runner.calls[-1]
    assert usage_call[:2] == ("-p", "--output-format")
    assert "--safe-mode" in usage_call
    assert "--no-session-persistence" in usage_call
    assert (
        usage_call[usage_call.index("--max-budget-usd") + 1]
        == CLAUDE_USAGE_PROBE_BUDGET_USD
    )
    assert "private@example.com" not in str(observation)


def test_claude_usage_probe_stops_on_api_auth_mode() -> None:
    runner = _runner(auth_payload={"authenticated": True, "authMode": "api_key"})

    observation = collect_claude_usage(
        _context(),
        runner=runner,
        clock=lambda: OBSERVED_AT,
    )

    assert observation["outcome"] == "not_applicable"
    assert observation["reason_code"] == "api_mode"
    assert observation["account_mode"] == "api"
    assert not any("/usage" in call for call in runner.calls)


def test_claude_usage_probe_returns_partial_for_unparseable_reset() -> None:
    runner = _runner(
        usage_text="Current session: 10% used - resets someday soon",
    )

    observation = collect_claude_usage(
        _context(),
        runner=runner,
        clock=lambda: OBSERVED_AT,
    )

    assert observation["outcome"] == "ok"
    assert observation["completeness"] == "partial"
    assert observation["reason_code"] == "parse_error"
    assert observation["windows"][0]["key"] == "session"
    assert observation["windows"][0]["resets_at"] is None


def test_claude_usage_probe_rejects_older_or_unverifiable_versions() -> None:
    runner = _runner(
        usage_text="Current session: 10% used - resets Sep 7, 6:30pm",
        version="2.1.200 (Claude Code)",
    )

    observation = collect_claude_usage(
        _context(),
        runner=runner,
        clock=lambda: OBSERVED_AT,
    )

    assert observation["outcome"] == "unsupported"
    assert observation["reason_code"] == "unsupported_cli_version"
    assert not any("/usage" in call for call in runner.calls)


def test_claude_usage_probe_requires_zero_turn_zero_cost_markers() -> None:
    runner = _runner(
        usage_payload={
            "type": "result",
            "result": "Current session: 10% used - resets Sep 7, 6:30pm",
            "total_cost_usd": 0,
            "num_turns": 1,
        }
    )

    observation = collect_claude_usage(
        _context(),
        runner=runner,
        clock=lambda: OBSERVED_AT,
    )

    assert observation["outcome"] == "error"
    assert observation["reason_code"] == "probe_failed"
    assert "zero-turn zero-cost" in str(observation["diagnostic"])


def test_claude_usage_probe_classifies_cli_option_rejection_as_vendor_drift() -> None:
    runner = _runner(
        usage_text="Current session: 10% used - resets Sep 7, 6:30pm",
    )
    runner.responses[_usage_tail()] = ClaudeCommandResult(
        1,
        "",
        _ZERO_BUDGET_ERROR + "\nignored continuation",
    )

    observation = collect_claude_usage(
        _context(),
        runner=runner,
        clock=lambda: OBSERVED_AT,
    )

    assert observation["outcome"] == "error"
    assert observation["reason_code"] == "vendor_drift"
    diagnostic = observation["diagnostic"]
    assert "claude /usage exited 1" in diagnostic
    assert "--max-budget-usd" in diagnostic
    assert "\n" not in diagnostic
    assert len(diagnostic) <= 200
    usage_calls = [call for call in runner.calls if "/usage" in call]
    assert usage_calls == [_usage_tail()]


def test_claude_reset_parser_handles_time_date_year_rollover_and_iso() -> None:
    ny = ZoneInfo("America/New_York")
    december = datetime(2026, 12, 31, 12, 0, tzinfo=ny).timestamp()
    september = datetime(2026, 9, 7, 18, 0, tzinfo=ny).timestamp()

    assert (
        parse_claude_reset_timestamp(
            "Jan 1, 8pm (America/New_York)",
            observed_at=december,
        )
        == datetime(2027, 1, 1, 20, 0, tzinfo=ny).timestamp()
    )
    assert (
        parse_claude_reset_timestamp("8pm", observed_at=september)
        == datetime(
            2026,
            9,
            7,
            20,
            0,
            tzinfo=ny,
        ).timestamp()
    )
    assert (
        parse_claude_reset_timestamp(
            "2026-09-08 18:30 UTC",
            observed_at=september,
        )
        == datetime(2026, 9, 8, 18, 30, tzinfo=ZoneInfo("UTC")).timestamp()
    )


def test_claude_rate_limit_event_normalizes_partial_windows() -> None:
    context = _context()
    event = {
        "type": "rate_limit_event",
        "rate_limit_info": {
            "status": "allowed",
            "unifiedWindows": {
                "five_hour": {"utilization": 0.1, "resetsAt": OBSERVED_AT + 1800},
                "seven_day": {"utilization": 0.25, "resetsAt": OBSERVED_AT + 3600},
            },
        },
    }

    observation = _claude_rate_limit_event_observation(
        event,
        context,
        now=OBSERVED_AT + 10.0,
    )

    assert observation is not None
    assert observation["source"] == "stream_event"
    assert observation["completeness"] == "partial"
    windows = {window["key"]: window for window in observation["windows"]}
    assert windows["session"]["used_percent"] == 10.0
    assert windows["weekly"]["used_percent"] == 25.0
    assert {window["vendor_state"] for window in windows.values()} == {"allowed"}


def test_claude_stream_usage_events_do_not_affect_compatible_runtimes() -> None:
    context = _context()
    event = {
        "type": "rate_limit_event",
        "rate_limit_info": {"unifiedWindows": {"five_hour": {"utilization": 0.1}}},
    }
    writer = Mock()

    with patch(
        "sase.llm_provider.usage.claude.submit_claude_passive_usage_event"
    ) as submit:
        _process_json_line(
            json.dumps(event),
            assistant_texts=[],
            suppress_output=True,
            runtime="codex",
            tool_call_writer=writer,
            usage_context=context,
        )

    submit.assert_not_called()
    writer.assert_called_once()


def test_claude_provider_exposes_usage_probe_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    provider = ClaudeCodeProvider()
    runner = _runner(
        usage_text="Current session: 10% used - resets Sep 7, 6:30pm (America/New_York)"
    )
    assert provider.llm_usage_capabilities() == {"probe": True, "passive_events": True}

    with patch(
        "sase.llm_provider.usage.claude._run_claude_command",
        side_effect=runner,
    ):
        result = run_usage_probe(
            _context(),
            isolate=False,
            plugin=provider,
            now=OBSERVED_AT,
        )

    assert result.observation is not None
    assert result.observation["outcome"] == "ok"


def test_passive_context_hashes_auth_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    runner = _runner()

    context = capture_claude_passive_usage_context(
        executable="/fake/bin/claude",
        runner=runner,
        clock=lambda: OBSERVED_AT,
    )

    assert context is not None
    assert context.context_id.startswith("claude-usage-")
    assert "private@example.com" not in context.context_id
