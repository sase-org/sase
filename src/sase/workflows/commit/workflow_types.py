"""Shared types and method names for the commit workflow."""

from enum import IntEnum

from sase.commit_methods import METHOD_ALIASES, VALID_METHODS

__all__ = [
    "RunResult",
    "EXIT_CODE_CONFLICT",
    "VALID_METHODS",
    "METHOD_ALIASES",
]


class RunResult(IntEnum):
    OK = 0
    FAILED = 1
    CONFLICT = 2


EXIT_CODE_CONFLICT = 2
