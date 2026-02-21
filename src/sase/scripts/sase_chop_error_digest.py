#!/usr/bin/env python3
"""Error digest notification chop script."""

import argparse
from datetime import datetime, timedelta

from sase.axe.chop_script_context import read_chop_context
from sase.axe.state import read_errors
from sase.notifications.senders import notify_axe_error_digest
from sase.sase_utils import EASTERN_TZ


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    args = parser.parse_args()

    # Read context (unused fields, but validates the context file)
    read_chop_context(args.context)

    errors = read_errors()
    cutoff = (datetime.now(EASTERN_TZ) - timedelta(hours=1)).isoformat()
    recent = [e for e in errors if e.get("timestamp", "") >= cutoff]
    if recent:
        notify_axe_error_digest(recent)


if __name__ == "__main__":
    main()
