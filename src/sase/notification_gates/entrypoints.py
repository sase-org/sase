"""Markers for gate commands invoked through generated bundle scripts."""

from collections.abc import Callable


def gate_command_entrypoint[FunctionT: Callable[..., object]](
    function: FunctionT,
) -> FunctionT:
    """Mark a function as a generated command-script entry point."""
    return function


__all__ = ["gate_command_entrypoint"]
