"""CLI capability cache for usage probes: warm/cold spawns, TTL, invalidation."""

from __future__ import annotations

import json
import os
import shutil
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.llm_provider.usage._capability_cache import (
    CAPABILITY_CACHE_TTL_SECONDS,
    _capability_cache_dir,
    _invalidate_probe_capability,
    decode_command_result,
    encode_command_result,
    executable_fingerprint,
    note_probe_capability_outcome,
    read_probe_capability,
    write_probe_capability,
)
from sase.llm_provider.usage._claude_support_command import (
    CLAUDE_USAGE_PROBE_BUDGET_USD,
    ClaudeCommandResult,
)
from sase.llm_provider.usage.agy import collect_agy_usage
from sase.llm_provider.usage.claude import collect_claude_usage
from sase.llm_provider.usage.grok import collect_grok_usage
from sase.llm_provider.usage.probe import default_probe_context

_AGY_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "usage_probe" / "agy_usage_cli.py"
)
_GROK_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "usage_probe" / "grok_acp_cli.py"
)
_NATIVE_GROK_VERSION = "grok 1.0.13 (72a61251fc) [stable]"

_CLAUDE_USAGE_TEXT = "\n".join(
    [
        "You are currently using your Claude Max subscription.",
        "Current session: 10% used - resets Sep 7, 6:30pm (America/New_York)",
        "Current week: 25% used - resets Sep 12, 8pm (America/New_York)",
    ]
)
_ZERO_BUDGET_ERROR = (
    "error: option '--max-budget-usd <amount>' argument '0' is invalid. "
    "--max-budget-usd must be a positive number greater than 0"
)

_GROK_WEEKLY_PAYLOAD = {
    "config": {
        "creditUsagePercent": 37.5,
        "currentPeriod": {
            "type": "USAGE_PERIOD_TYPE_WEEKLY",
            "start": "2027-01-15T00:00:00Z",
            "end": "2027-01-22T00:00:00Z",
        },
        "subscriptionTier": "SuperGrok Heavy",
    }
}


def _cache_path(provider: str) -> Path:
    return _capability_cache_dir() / f"{provider}.json"


class FakeClaudeRunner:
    """Scripted Claude command runner that records every spawn."""

    def __init__(self, usage_stdout: str) -> None:
        self.responses = {
            ("--version",): ClaudeCommandResult(0, "2.1.263 (Claude Code)", ""),
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
                    {
                        "authenticated": True,
                        "authType": "oauth",
                        "account": {"email": "private@example.com"},
                        "plan": "Max",
                    }
                ),
                "",
            ),
        }
        self.usage_stdout = usage_stdout
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
        if tail == self.usage_tail():
            override = self.usage_override(tail)
            if override is not None:
                return override
            return ClaudeCommandResult(0, json.dumps(self.usage_payload()), "")
        return self.responses[tail]

    @staticmethod
    def usage_tail() -> tuple[str, ...]:
        return (
            "-p",
            "--output-format",
            "json",
            "--safe-mode",
            "--no-session-persistence",
            "--permission-prompts",
            "none",
            "--max-budget-usd",
            CLAUDE_USAGE_PROBE_BUDGET_USD,
            "/usage",
        )

    def usage_override(self, tail: tuple[str, ...]) -> ClaudeCommandResult | None:
        """Return a scripted ``/usage`` failure, or ``None`` for success."""
        del tail
        return None

    def usage_payload(self) -> dict[str, Any]:
        return {
            "type": "result",
            "result": self.usage_stdout,
            "total_cost_usd": 0,
            "num_turns": 0,
        }


def _make_fake_executable(tmp_path: Path, name: str, fixture: Path) -> Path:
    path = tmp_path / name
    shutil.copy(fixture, path)
    path.chmod(0o755)
    return path


def _read_json_lines(path: Path) -> list[Any]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_capability_cache_round_trip_and_expiry() -> None:
    now = time.time()
    capabilities = {"version": {"returncode": 0, "stdout": "1.2.7\n", "stderr": ""}}
    write_probe_capability("agy", "fp-1", capabilities, now=now)
    assert read_probe_capability("agy", "fp-1", now=now) == capabilities
    assert (
        read_probe_capability(
            "agy", "fp-1", now=now + CAPABILITY_CACHE_TTL_SECONDS + 1.0
        )
        is None
    )


def test_capability_cache_fingerprint_change_is_miss() -> None:
    now = time.time()
    write_probe_capability(
        "grok",
        "fp-1",
        {"version": {"returncode": 0, "stdout": "v\n", "stderr": ""}},
        now=now,
    )
    assert read_probe_capability("grok", "fp-2", now=now) is None


def test_capability_cache_corrupt_entry_is_miss() -> None:
    now = time.time()
    path = _cache_path("claude")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("this is not json{{{", encoding="utf-8")
    assert read_probe_capability("claude", "fp-1", now=now) is None
    path.write_text(json.dumps({"fingerprint": "fp-1"}), encoding="utf-8")
    assert read_probe_capability("claude", "fp-1", now=now) is None


def test_capability_cache_command_result_codec() -> None:
    encoded = encode_command_result(0, "out\n", "err\n")
    assert encoded is not None
    assert decode_command_result(encoded) == (0, "out\n", "err\n")
    assert decode_command_result({"returncode": 0}) is None
    assert decode_command_result("nope") is None
    assert encode_command_result(0, "x" * 70_000, "") is None
    assert executable_fingerprint("/nonexistent/sase-capability-probe") is None
    assert executable_fingerprint(None) is None


def test_note_probe_capability_outcome_invalidates_only_on_drift() -> None:
    now = time.time()
    for reason in ("unsupported_cli_version", "vendor_drift"):
        write_probe_capability(
            "agy",
            "fp",
            {"version": {"returncode": 0, "stdout": "v", "stderr": ""}},
            now=now,
        )
        note_probe_capability_outcome(
            "agy", {"outcome": "error", "reason_code": reason}
        )
        assert not _cache_path("agy").exists()
    for reason in (None, "rate_limited", "timeout", "probe_failed"):
        write_probe_capability(
            "agy",
            "fp",
            {"version": {"returncode": 0, "stdout": "v", "stderr": ""}},
            now=now,
        )
        note_probe_capability_outcome(
            "agy", {"outcome": "error", "reason_code": reason}
        )
        assert _cache_path("agy").exists()
    _invalidate_probe_capability("agy")
    note_probe_capability_outcome("agy", None)


def test_claude_warm_probe_spawns_two_processes_instead_of_five(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "claude"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    context = default_probe_context(
        "claude", executable=str(executable), deadline_seconds=30.0
    )
    cold = FakeClaudeRunner(_CLAUDE_USAGE_TEXT)
    observation = collect_claude_usage(context, runner=cold, clock=time.time)
    assert observation["outcome"] == "ok"
    assert len(cold.calls) == 5
    assert _cache_path("claude").exists()

    warm = FakeClaudeRunner(_CLAUDE_USAGE_TEXT)
    observation = collect_claude_usage(context, runner=warm, clock=time.time)
    assert observation["outcome"] == "ok"
    assert [call[0] for call in warm.calls] == ["auth", "-p"]


def test_claude_fingerprint_change_reprobes_from_scratch(tmp_path: Path) -> None:
    executable = tmp_path / "claude"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    context = default_probe_context(
        "claude", executable=str(executable), deadline_seconds=30.0
    )
    cold = FakeClaudeRunner(_CLAUDE_USAGE_TEXT)
    assert collect_claude_usage(context, runner=cold, clock=time.time)["outcome"] == (
        "ok"
    )
    assert len(cold.calls) == 5

    executable.write_text("#!/bin/sh\nexit 0 # updated\n", encoding="utf-8")
    reprobe = FakeClaudeRunner(_CLAUDE_USAGE_TEXT)
    assert (
        collect_claude_usage(context, runner=reprobe, clock=time.time)["outcome"]
        == "ok"
    )
    assert len(reprobe.calls) == 5


def test_claude_vendor_drift_invalidates_capability_cache(tmp_path: Path) -> None:
    executable = tmp_path / "claude"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    context = default_probe_context(
        "claude", executable=str(executable), deadline_seconds=30.0
    )
    cold = FakeClaudeRunner(_CLAUDE_USAGE_TEXT)
    assert collect_claude_usage(context, runner=cold, clock=time.time)["outcome"] == (
        "ok"
    )
    assert _cache_path("claude").exists()

    class DriftRunner(FakeClaudeRunner):
        def usage_override(self, tail: tuple[str, ...]) -> ClaudeCommandResult | None:
            del tail
            return ClaudeCommandResult(1, "", _ZERO_BUDGET_ERROR)

    drift = DriftRunner(_CLAUDE_USAGE_TEXT)
    observation = collect_claude_usage(context, runner=drift, clock=time.time)
    assert observation["reason_code"] == "vendor_drift"
    assert not _cache_path("claude").exists()


def test_claude_unsupported_version_invalidates_capability_cache(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "claude"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fingerprint = executable_fingerprint(str(executable))
    assert fingerprint is not None
    write_probe_capability(
        "claude",
        fingerprint,
        {
            "version": {
                "returncode": 0,
                "stdout": "2.1.263 (Claude Code)",
                "stderr": "",
            },
            "print_help": {"returncode": 0, "stdout": "stale", "stderr": ""},
            "auth_help": {"returncode": 0, "stdout": "--json", "stderr": ""},
        },
    )
    context = default_probe_context(
        "claude", executable=str(executable), deadline_seconds=30.0
    )
    runner = FakeClaudeRunner(_CLAUDE_USAGE_TEXT)
    runner.responses[("--version",)] = ClaudeCommandResult(0, "1.0.0", "")
    observation = collect_claude_usage(context, runner=runner, clock=time.time)
    assert observation["reason_code"] == "unsupported_cli_version"
    assert not _cache_path("claude").exists()


def test_agy_warm_probe_skips_version_spawn(tmp_path: Path, monkeypatch: Any) -> None:
    fake = _make_fake_executable(tmp_path, "agy", _AGY_FIXTURE)
    argv_path = tmp_path / "argv.jsonl"
    monkeypatch.setenv("SASE_FAKE_AGY_MODE", "success")
    monkeypatch.setenv("SASE_FAKE_AGY_VERSION", "1.2.7")
    monkeypatch.setenv("SASE_FAKE_AGY_ARGV", str(argv_path))

    def probe() -> Mapping[str, Any]:
        context = default_probe_context(
            "agy",
            executable=str(fake),
            working_directory=str(tmp_path),
            deadline_seconds=30.0,
        )
        return collect_agy_usage(context)

    assert probe()["outcome"] == "ok"
    cold_argv = [entry["argv"] for entry in _read_json_lines(argv_path)]
    assert cold_argv[0] == ["--version"]
    assert any(argv[:2] == ["-p", "/usage"] for argv in cold_argv)
    assert _cache_path("agy").exists()

    argv_path.unlink()
    assert probe()["outcome"] == "ok"
    warm_argv = [entry["argv"] for entry in _read_json_lines(argv_path)]
    assert len(warm_argv) == 1
    assert warm_argv[0][:2] == ["-p", "/usage"]


def test_agy_unsupported_version_invalidates_capability_cache(
    tmp_path: Path, monkeypatch: Any
) -> None:
    fake = _make_fake_executable(tmp_path, "agy", _AGY_FIXTURE)
    argv_path = tmp_path / "argv.jsonl"
    monkeypatch.setenv("SASE_FAKE_AGY_MODE", "success")
    monkeypatch.setenv("SASE_FAKE_AGY_VERSION", "1.2.7")
    monkeypatch.setenv("SASE_FAKE_AGY_ARGV", str(argv_path))
    context = default_probe_context(
        "agy",
        executable=str(fake),
        working_directory=str(tmp_path),
        deadline_seconds=30.0,
    )
    assert collect_agy_usage(context)["outcome"] == "ok"
    assert _cache_path("agy").exists()

    with fake.open("ab") as handle:
        handle.write(b"# changed\n")
    monkeypatch.setenv("SASE_FAKE_AGY_VERSION_EXIT", "1")
    observation = collect_agy_usage(context)
    assert observation["reason_code"] == "unsupported_cli_version"
    assert not _cache_path("agy").exists()


def test_grok_warm_probe_skips_version_spawn(tmp_path: Path, monkeypatch: Any) -> None:
    fake = _make_fake_executable(tmp_path, "grok", _GROK_FIXTURE)
    argv_path = tmp_path / "argv.jsonl"
    messages_path = tmp_path / "messages.jsonl"
    monkeypatch.setenv("SASE_FAKE_GROK_MODE", "native")
    monkeypatch.setenv("SASE_FAKE_GROK_VERSION", _NATIVE_GROK_VERSION)
    monkeypatch.setenv("SASE_FAKE_GROK_ARGV", str(argv_path))
    monkeypatch.setenv("SASE_FAKE_GROK_MESSAGES", str(messages_path))
    monkeypatch.setenv("SASE_FAKE_GROK_BILLING", json.dumps(_GROK_WEEKLY_PAYLOAD))

    def probe() -> Mapping[str, Any]:
        context = default_probe_context(
            "grok", executable=str(fake), deadline_seconds=30.0
        )
        return collect_grok_usage(context)

    assert probe()["outcome"] == "ok"
    cold_argv = _read_json_lines(argv_path)
    assert ["--version"] in cold_argv
    assert ["--no-auto-update", "agent", "stdio"] in cold_argv
    assert _cache_path("grok").exists()

    argv_path.unlink()
    assert probe()["outcome"] == "ok"
    warm_argv = _read_json_lines(argv_path)
    assert ["--version"] not in warm_argv
    assert ["--no-auto-update", "agent", "stdio"] in warm_argv


def test_agy_bare_command_name_resolves_through_path(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A bare ``agy`` on PATH fingerprints, so the warm probe skips ``--version``.

    In production the runner's probe context carries no executable and the
    probe passes the bare command name; without PATH resolution the
    fingerprint is ``None`` and the cache never hits.
    """
    _make_fake_executable(tmp_path, "agy", _AGY_FIXTURE)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))
    argv_path = tmp_path / "argv.jsonl"
    monkeypatch.setenv("SASE_FAKE_AGY_MODE", "success")
    monkeypatch.setenv("SASE_FAKE_AGY_VERSION", "1.2.7")
    monkeypatch.setenv("SASE_FAKE_AGY_ARGV", str(argv_path))

    def probe() -> Mapping[str, Any]:
        context = default_probe_context(
            "agy",
            working_directory=str(tmp_path),
            deadline_seconds=30.0,
        )
        return collect_agy_usage(context)

    assert executable_fingerprint("agy") is not None
    assert probe()["outcome"] == "ok"
    cold_argv = [entry["argv"] for entry in _read_json_lines(argv_path)]
    assert cold_argv[0] == ["--version"]
    assert any(argv[:2] == ["-p", "/usage"] for argv in cold_argv)
    assert _cache_path("agy").exists()

    argv_path.unlink()
    assert probe()["outcome"] == "ok"
    warm_argv = [entry["argv"] for entry in _read_json_lines(argv_path)]
    assert len(warm_argv) == 1
    assert warm_argv[0][:2] == ["-p", "/usage"]


def test_grok_bare_command_name_resolves_through_path(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A bare ``grok`` on PATH fingerprints, so the warm probe skips ``--version``."""
    _make_fake_executable(tmp_path, "grok", _GROK_FIXTURE)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))
    argv_path = tmp_path / "argv.jsonl"
    messages_path = tmp_path / "messages.jsonl"
    monkeypatch.setenv("SASE_FAKE_GROK_MODE", "native")
    monkeypatch.setenv("SASE_FAKE_GROK_VERSION", _NATIVE_GROK_VERSION)
    monkeypatch.setenv("SASE_FAKE_GROK_ARGV", str(argv_path))
    monkeypatch.setenv("SASE_FAKE_GROK_MESSAGES", str(messages_path))
    monkeypatch.setenv("SASE_FAKE_GROK_BILLING", json.dumps(_GROK_WEEKLY_PAYLOAD))

    def probe() -> Mapping[str, Any]:
        context = default_probe_context("grok", deadline_seconds=30.0)
        return collect_grok_usage(context)

    assert executable_fingerprint("grok") is not None
    assert probe()["outcome"] == "ok"
    assert ["--version"] in _read_json_lines(argv_path)
    assert _cache_path("grok").exists()

    argv_path.unlink()
    assert probe()["outcome"] == "ok"
    warm_argv = _read_json_lines(argv_path)
    assert ["--version"] not in warm_argv
    assert ["--no-auto-update", "agent", "stdio"] in warm_argv


def test_grok_missing_billing_method_invalidates_capability_cache(
    tmp_path: Path, monkeypatch: Any
) -> None:
    fake = _make_fake_executable(tmp_path, "grok", _GROK_FIXTURE)
    argv_path = tmp_path / "argv.jsonl"
    messages_path = tmp_path / "messages.jsonl"
    monkeypatch.setenv("SASE_FAKE_GROK_MODE", "native")
    monkeypatch.setenv("SASE_FAKE_GROK_VERSION", _NATIVE_GROK_VERSION)
    monkeypatch.setenv("SASE_FAKE_GROK_ARGV", str(argv_path))
    monkeypatch.setenv("SASE_FAKE_GROK_MESSAGES", str(messages_path))
    monkeypatch.setenv("SASE_FAKE_GROK_BILLING", json.dumps(_GROK_WEEKLY_PAYLOAD))

    def probe() -> Mapping[str, Any]:
        context = default_probe_context(
            "grok", executable=str(fake), deadline_seconds=30.0
        )
        return collect_grok_usage(context)

    assert probe()["outcome"] == "ok"
    assert _cache_path("grok").exists()

    monkeypatch.setenv("SASE_FAKE_GROK_MODE", "method_missing")
    observation = probe()
    assert observation["reason_code"] == "vendor_drift"
    assert not _cache_path("grok").exists()
