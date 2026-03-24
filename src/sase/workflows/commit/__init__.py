"""Workflow for dispatching VCS commit operations."""

import json
import os
import sys
from typing import NoReturn

from .workflow import CommitWorkflow

# Public API
__all__ = [
    "CommitWorkflow",
    "main",
]


def main() -> NoReturn:
    """Main entry point for the commit workflow (standalone execution)."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Dispatch a VCS commit operation via JSON payload."
    )
    parser.add_argument(
        "payload",
        help="JSON string describing the commit operation",
    )
    parser.add_argument(
        "-m",
        "--method",
        help="Commit method: create_commit, create_proposal, or create_pull_request. "
        "Overrides $SASE_COMMIT_METHOD env var.",
    )

    args = parser.parse_args()

    try:
        payload = json.loads(args.payload)
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON payload: {exc}", file=sys.stderr)
        sys.exit(1)

    method = args.method or os.environ.get("SASE_COMMIT_METHOD", "create_commit")

    workflow = CommitWorkflow(payload=payload, method=method)
    success = workflow.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
