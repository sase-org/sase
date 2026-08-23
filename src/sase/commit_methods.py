"""Commit method constants.

This module must stay dependency-free: argparse ``choices`` for
``sase stitch create`` import it directly so building that parser never
pulls in the full commit workflow dependency chain.
"""

VALID_METHODS = ("create_commit", "create_proposal", "create_pull_request")

METHOD_ALIASES: dict[str, str] = {
    "commit": "create_commit",
    "propose": "create_proposal",
    "pr": "create_pull_request",
}
