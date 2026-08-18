"""Handler for the top-level ``sase validate`` command."""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from typing import NoReturn

from sase.agents.cli_prompts import PROMPT_ARCHIVE_CONTEXT_UNAVAILABLE_EXIT_CODE


@dataclass(frozen=True)
class _ValidationCheck:
    label: str
    argv: tuple[str, ...]
    skip_returncodes: tuple[int, ...] = ()


@dataclass(frozen=True)
class _ValidationResult:
    check: _ValidationCheck
    returncode: int
    stdout: str
    stderr: str


_CHECKS = (
    # Machine identity is intentionally local and may be absent on a clean CI
    # host. Validate portable initialization surfaces explicitly; users and
    # doctor still get the full Config-first plan from bare `sase init --check`.
    _ValidationCheck("init memory --check", ("init", "memory", "--check")),
    _ValidationCheck("init repo --check", ("init", "repo", "--check")),
    _ValidationCheck("init skills --check", ("init", "skills", "--check")),
    _ValidationCheck(
        "doctor config.file_hooks",
        ("doctor", "-C", "config.file_hooks"),
    ),
    _ValidationCheck(
        "plan links validate",
        ("plan", "links", "validate"),
    ),
    _ValidationCheck(
        "agent prompts validate",
        ("agent", "prompts", "validate"),
        (PROMPT_ARCHIVE_CONTEXT_UNAVAILABLE_EXIT_CODE,),
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
    return 0 if all(_is_success(result) for result in results) else 1


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
        status = (
            "ok"
            if result.returncode == 0
            else "skip"
            if _is_skipped(result)
            else "fail"
        )
        print(f"  {status:<6} {result.check.label}")

    _print_passing_warnings(results)

    for result in results:
        if result.returncode == 0:
            continue
        if _is_skipped(result):
            _print_skip(result)
        else:
            _print_failure(result)
    if any(not _is_success(result) for result in results):
        print()
        print(_SUPPORT_HINT)


def _print_passing_warnings(results: list[_ValidationResult]) -> None:
    """Surface warnings a passing check reported without failing it.

    A check can exit 0 and still print its own ``Warnings:`` section (for
    example ``init skills --check`` deferring a chezmoi redeploy). Only the
    non-zero branch of ``_print_results`` dumped a check's stdout, so those
    warnings were silently dropped from ``sase validate`` output even though
    they were the whole point of the check passing with caveats.
    """
    warnings = [
        warning
        for result in results
        if result.returncode == 0
        for warning in _extract_check_warnings(result.stdout)
    ]
    if not warnings:
        return
    print()
    print("Warnings:")
    for warning in warnings:
        print(f"  {warning}")


def _extract_check_warnings(stdout: str) -> list[str]:
    """Return warning lines from a ``Warnings:`` section in *stdout*, if any."""
    lines = stdout.splitlines()
    try:
        start = lines.index("Warnings:")
    except ValueError:
        return []
    warnings: list[str] = []
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if not stripped:
            break
        warnings.append(stripped)
    return warnings


def _is_skipped(result: _ValidationResult) -> bool:
    return result.returncode in result.check.skip_returncodes


def _is_success(result: _ValidationResult) -> bool:
    return result.returncode == 0 or _is_skipped(result)


def _print_skip(result: _ValidationResult) -> None:
    print()
    print(f"{result.check.label} skipped (exit {result.returncode})")
    _print_result_output(result)


def _print_failure(result: _ValidationResult) -> None:
    print()
    print(f"{result.check.label} failed (exit {result.returncode})")
    _print_result_output(result)


def _print_result_output(result: _ValidationResult) -> None:
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
