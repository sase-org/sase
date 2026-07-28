"""Shared types and method names for the commit workflow."""

from enum import IntEnum


class RunResult(IntEnum):
    OK = 0
    FAILED = 1
    CONFLICT = 2


EXIT_CODE_CONFLICT = 2

VALID_METHODS = ("create_commit", "create_proposal", "create_pull_request")

METHOD_ALIASES: dict[str, str] = {
    "commit": "create_commit",
    "propose": "create_proposal",
    "pr": "create_pull_request",
}
