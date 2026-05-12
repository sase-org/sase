#!/usr/bin/env python3
"""Error digest notification chop script."""

import argparse
from datetime import datetime, timedelta

from sase.axe.chop_script_context import read_chop_context
from sase.axe.state import (
    read_errors,
    read_last_error_digest_ts,
    write_last_error_digest_ts,
)
from sase.notifications.senders import notify_axe_error_digest
from sase.core.time import get_timezone


def _emit_summary(
    *,
    errors_total: int,
    recent_count: int,
    notified_count: int,
    effective_cutoff: str,
    newest_ts: str | None,
) -> None:
    parts = [
        "error_digest:",
        f"errors_total={errors_total}",
        f"recent={recent_count}",
        f"notified={notified_count}",
        f"cutoff={effective_cutoff}",
        f"newest={newest_ts or '-'}",
    ]
    if recent_count == 0:
        parts.append("reason=no_recent_errors")
    print(" ".join(parts))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    args = parser.parse_args()

    # Read context (unused fields, but validates the context file)
    read_chop_context(args.context)

    errors = read_errors()
    cutoff = (datetime.now(get_timezone()) - timedelta(hours=1)).isoformat()
    last_digest_ts = read_last_error_digest_ts()
    effective_cutoff = max(cutoff, last_digest_ts) if last_digest_ts else cutoff
    recent = [e for e in errors if e.get("timestamp", "") > effective_cutoff]
    newest_ts = None
    notified_count = 0
    if recent:
        notify_axe_error_digest(recent)
        notified_count = len(recent)
        newest_ts = max(e["timestamp"] for e in recent)
        write_last_error_digest_ts(newest_ts)
    _emit_summary(
        errors_total=len(errors),
        recent_count=len(recent),
        notified_count=notified_count,
        effective_cutoff=effective_cutoff,
        newest_ts=newest_ts,
    )


if __name__ == "__main__":
    main()
