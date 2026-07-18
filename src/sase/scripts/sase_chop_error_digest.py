#!/usr/bin/env python3
"""Error digest notification chop script."""

from datetime import datetime, timedelta

from sase.axe.state import (
    read_errors,
    read_last_error_digest_ts,
    write_last_error_digest_ts,
)
from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.notifications.senders import notify_axe_error_digest
from sase.core.time import get_timezone


@builtin_chop("error_digest")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
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
    return runtime.emit_summary(
        {
            "errors_total": len(errors),
            "recent": len(recent),
            "notified": notified_count,
            "cutoff": effective_cutoff,
            "newest": newest_ts,
        },
        reason="no_recent_errors" if not recent else None,
    )


def main() -> None:
    run_builtin_chop("error_digest")


if __name__ == "__main__":
    main()
