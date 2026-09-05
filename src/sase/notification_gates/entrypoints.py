"""Helpers for gate commands invoked through generated bundle scripts."""

import shlex
import sys
from collections.abc import Callable


def gate_command_entrypoint[FunctionT: Callable[..., object]](
    function: FunctionT,
) -> FunctionT:
    """Mark a function as a generated command-script entry point."""
    return function


def python_gate_command_script(body: str) -> str:
    """Return a Python command script that tolerates spaces in sys.executable."""
    body = body if body.endswith("\n") else f"{body}\n"
    return f'#!/bin/sh\n"exec" {shlex.quote(sys.executable)} "$0" "$@"\n{body}'


__all__ = ["gate_command_entrypoint", "python_gate_command_script"]
