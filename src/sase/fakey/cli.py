"""Command-line entry point for the deterministic fakey agent."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from collections.abc import Mapping, Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from sase.fakey.scenario import (
    ResolvedScenario,
    ScenarioError,
    bundled_scenarios,
    resolve_scenario,
    select_attempt,
)
from sase.fakey.state import reserve_invocation, write_invocation


class _Terminated(Exception):
    pass


class _HelpParser(argparse.ArgumentParser):
    def print_help(self, file: Any = None) -> None:
        output = self.format_help()
        if "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb":
            output = output.replace("usage:", "\033[1;36musage:\033[0m", 1)
            for heading in ("options:",):
                output = output.replace(heading, f"\033[1;35m{heading}\033[0m")
            output = output.replace(
                "Scenario grammar:", "\033[1;33mScenario grammar:\033[0m"
            )
        print(output, end="", file=file or sys.stdout)


def _package_version() -> str:
    try:
        return version("sase")
    except PackageNotFoundError:
        return "unknown"


def _parser() -> argparse.ArgumentParser:
    parser = _HelpParser(
        prog="fakey",
        add_help=False,
        description=(
            "Run a deterministic fake agent using a layered YAML scenario. "
            "The prompt is read from stdin."
        ),
        epilog=(
            "Scenario grammar:\n"
            "  reply: text\n"
            "  attempts:\n"
            "    - fail: {message: unavailable, retryable: true, exit_code: 1}\n"
            "    - succeed: {reply: recovered}\n"
            "Embed the same YAML in a fenced ```fakey prompt block, pass a file, "
            "or use a bundled name such as @flaky."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-e", "--effort", metavar="LEVEL", help="record the requested effort level"
    )
    parser.add_argument(
        "-x",
        "--explain",
        action="store_true",
        help="print the resolved scenario as YAML and exit",
    )
    parser.add_argument(
        "-h", "--help", action="help", help="show this help message and exit"
    )
    parser.add_argument(
        "-l",
        "--list-scenarios",
        action="store_true",
        help="list bundled scenario names and exit",
    )
    parser.add_argument(
        "-m", "--model", metavar="MODEL", help="record the selected model"
    )
    parser.add_argument(
        "-s",
        "--scenario",
        metavar="PATH|@NAME",
        help="load a scenario file or bundled named scenario",
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"fakey {_package_version()}"
    )
    return parser


def _selected_env(env: Mapping[str, str]) -> dict[str, str]:
    selected = {
        key: value
        for key, value in env.items()
        if key.startswith("FAKEY_") or key == "SASE_ARTIFACTS_DIR"
    }
    return dict(sorted(selected.items()))


def _sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def _wait_for(value: Any, default_timeout: float) -> None:
    if isinstance(value, str):
        path = Path(value).expanduser()
        timeout = default_timeout
    else:
        path = Path(value["path"]).expanduser()
        timeout = float(value.get("timeout", default_timeout))
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError(f"wait_for timed out after {timeout:g}s: {path}")
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))


def _run_steps(steps: Sequence[Mapping[str, Any]], default_timeout: float) -> None:
    for step in steps:
        action, value = next(iter(step.items()))
        if action == "signal":
            path = Path(value).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        elif action == "sleep":
            _sleep(float(value))
        else:
            _wait_for(value, default_timeout)


def _emit_reply(reply: str, stream: Mapping[str, Any] | None) -> None:
    if stream is None:
        print(reply, flush=True)
        return
    chunk_delay = float(stream.get("chunk_delay", 0.05))
    lines = reply.splitlines() or [""]
    for line in lines:
        print(line, flush=True)
        _sleep(chunk_delay)


def _record(
    resolved: ResolvedScenario,
    invocation_number: int,
    *,
    argv: Sequence[str],
    prompt: str,
    model: str | None,
    effort: str | None,
    extras: Sequence[str],
    attempt_index: int,
    behavior: Mapping[str, Any],
    outcome: Mapping[str, Any],
) -> None:
    write_invocation(
        resolved.state_dir,
        invocation_number,
        {
            "argv": list(argv),
            "attempt_index": attempt_index,
            "effort": effort,
            "environment": _selected_env(os.environ),
            "extra_args": list(extras),
            "model": model,
            "outcome": dict(outcome),
            "prompt": prompt,
            "resolved_attempt": dict(behavior),
            "resolved_scenario": resolved.data,
            "scenario_source": resolved.source,
        },
    )


def _list_scenarios() -> None:
    for name, path in bundled_scenarios().items():
        loaded = yaml.safe_load(path.read_text()) or {}
        description = loaded.get("description") if isinstance(loaded, dict) else None
        suffix = f" — {description}" if description else ""
        print(f"@{name}{suffix}")


def _run(argv: Sequence[str] | None = None) -> int:
    actual_argv = list(sys.argv[1:] if argv is None else argv)
    args, extras = _parser().parse_known_args(actual_argv)
    if args.list_scenarios:
        _list_scenarios()
        return 0

    prompt = sys.stdin.read()
    try:
        resolved = resolve_scenario(prompt, selector=args.scenario)
    except ScenarioError as exc:
        print(f"fakey: error: {exc}", file=sys.stderr)
        return 2

    if args.explain:
        print(yaml.safe_dump(resolved.data, sort_keys=False), end="")
        return 0

    attempt_index, invocation_number = reserve_invocation(
        resolved.state_dir, resolved.state_key
    )
    behavior = select_attempt(resolved.data, attempt_index)
    outcome: dict[str, Any] = {"exit_code": 1, "status": "internal_error"}

    def terminate(_signum: int, _frame: Any) -> None:
        raise _Terminated

    previous_handler = signal.signal(signal.SIGTERM, terminate)
    try:
        _run_steps(
            behavior.get("steps", []),
            float(behavior.get("barrier_timeout", 30.0)),
        )
        _sleep(float(behavior.get("delay", 0.0)))
        if "fail" in behavior:
            failure = behavior["fail"]
            retryable = bool(failure.get("retryable", False))
            marker = "FAKEY-RETRYABLE" if retryable else "FAKEY-FAIL"
            message = str(failure.get("message", "simulated failure"))
            channel = failure.get("channel", "stderr")
            destination = sys.stdout if channel == "stdout" else sys.stderr
            print(f"{marker}: {message}", file=destination, flush=True)
            exit_code = int(failure.get("exit_code", 1))
            outcome = {
                "channel": channel,
                "exit_code": exit_code,
                "marker": marker,
                "status": "failed",
            }
            return exit_code

        _emit_reply(str(behavior.get("reply", "")), behavior.get("stream"))
        usage = behavior.get("usage")
        if usage is not None:
            print(f"FAKEY-USAGE: {json.dumps(usage, sort_keys=True)}", flush=True)
        outcome = {"exit_code": 0, "status": "succeeded"}
        return 0
    except TimeoutError as exc:
        print(f"FAKEY-FAIL: {exc}", file=sys.stderr, flush=True)
        outcome = {"exit_code": 124, "message": str(exc), "status": "timed_out"}
        return 124
    except _Terminated:
        outcome = {"exit_code": 143, "status": "terminated"}
        return 143
    finally:
        signal.signal(signal.SIGTERM, previous_handler)
        _record(
            resolved,
            invocation_number,
            argv=actual_argv,
            prompt=prompt,
            model=args.model,
            effort=args.effort,
            extras=extras,
            attempt_index=attempt_index,
            behavior=behavior,
            outcome=outcome,
        )


def main() -> None:
    raise SystemExit(_run())


if __name__ == "__main__":
    main()
