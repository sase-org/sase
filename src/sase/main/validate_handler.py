"""Handler for the top-level ``sase validate`` command."""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from typing import NoReturn


@dataclass(frozen=True)
class _ValidationCheck:
    label: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class _ValidationResult:
    check: _ValidationCheck
    returncode: int
    stdout: str
    stderr: str


_CHECKS = (
    _ValidationCheck("init --check", ("init", "--check")),
    _ValidationCheck(
        "plan links validate",
        ("plan", "links", "validate"),
    ),
)

_SUPPORT_HINT = (
    "For broader diagnostics, run `sase doctor -v` or `sase doctor -j` "
    "and attach the output when asking for help."
)


def handle_validate_command(args: argparse.Namespace) -> NoReturn:
    """Run validation checks and exit with the aggregate status."""
    del args
    sys.exit(_run_validate_command())


def _run_validate_command() -> int:
    """Run every SASE validation check and return a process exit code."""
    results = [_run_check(check) for check in _CHECKS]
    _print_results(results)
    return 0 if all(result.returncode == 0 for result in results) else 1


def _run_check(check: _ValidationCheck) -> _ValidationResult:
    command = [sys.executable, "-m", "sase", *check.argv]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return _ValidationResult(
            check=check,
            returncode=1,
            stdout="",
            stderr=str(exc),
        )
    return _ValidationResult(
        check=check,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _print_results(results: list[_ValidationResult]) -> None:
    print("SASE validation")
    for result in results:
        status = "ok" if result.returncode == 0 else "fail"
        print(f"  {status:<6} {result.check.label}")

    for result in results:
        if result.returncode == 0:
            continue
        _print_failure(result)
    if any(result.returncode != 0 for result in results):
        print()
        print(_SUPPORT_HINT)


def _print_failure(result: _ValidationResult) -> None:
    print()
    print(f"{result.check.label} failed (exit {result.returncode})")
    had_output = False
    if result.stdout:
        had_output = True
        _print_stream("stdout", result.stdout)
    if result.stderr:
        had_output = True
        _print_stream("stderr", result.stderr)
    if not had_output:
        print("no output")


def _print_stream(label: str, output: str) -> None:
    text = output.rstrip()
    if not text:
        return
    print(f"{label}:")
    print(text)
