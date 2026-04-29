#!/usr/bin/env python3
"""Comment check cycle chop script."""

import argparse

from sase.axe.check_cycles import CheckCycleRunner
from sase.axe.chop_script_context import read_chop_context


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    args = parser.parse_args()

    ctx = read_chop_context(args.context)

    def log(message: str, style: str | None = None) -> None:
        print(message)

    runner = CheckCycleRunner(ctx.query or None, log)
    runner.run_comment_check_cycle()


if __name__ == "__main__":
    main()
