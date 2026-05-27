"""Command-line parsing for the chat install worker module."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path


def main(argv: list[str] | None, *, run_worker: Callable[..., int]) -> int:
    parser = argparse.ArgumentParser(prog="python -m sase.integrations.chat_install")
    parser.add_argument("--workspace", required=True, help="Primary SASE workspace")
    parser.add_argument("--job-id", default=None, help="Chat install job id")
    parser.add_argument(
        "--status-path",
        default=None,
        help="Path to write the final chat install completion JSON",
    )
    parser.add_argument("--log-path", default=None, help="Worker log path")
    args = parser.parse_args(argv)
    return run_worker(
        Path(args.workspace).expanduser().resolve(),
        job_id=args.job_id,
        status_path=Path(args.status_path).expanduser() if args.status_path else None,
        log_path=Path(args.log_path).expanduser() if args.log_path else None,
    )
