#!/usr/bin/env python3
"""Compact the live notification JSONL store into the archive.

Runs on the hourly ``housekeeping`` lumberjack rather than on an interactive
path: compact-on-read of a multi-megabyte ``notifications.jsonl`` is the
work the ACE refresh cadence must not keep paying.
"""

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.notifications.store import compact_notification_store


def _reason_for(
    live_exists: bool,
    archived_count: int,
    externalized_count: int,
    broken_files_dropped: int,
) -> str | None:
    if not live_exists:
        return "store_missing"
    if not archived_count and not externalized_count and not broken_files_dropped:
        return "nothing_archived"
    return None


@builtin_chop("notification_store_compact")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    outcome = compact_notification_store()
    if (
        outcome.archived_count
        or outcome.externalized_count
        or outcome.broken_files_dropped
    ):
        runtime.log(
            (
                f"externalized {outcome.externalized_count} payloads, "
                f"pruned {outcome.broken_files_dropped} broken files references, "
                f"archived {outcome.archived_count} dismissed notifications "
                f"({outcome.live_bytes_before} -> {outcome.live_bytes_after} bytes)"
            ),
            "cyan",
        )
    return runtime.emit_summary(
        {
            "archived": outcome.archived_count,
            "externalized": outcome.externalized_count,
            "broken_files_dropped": outcome.broken_files_dropped,
            "live_bytes_before": outcome.live_bytes_before,
            "live_bytes_after": outcome.live_bytes_after,
            "live_rows": outcome.live_rows_after,
        },
        reason=_reason_for(
            outcome.live_exists,
            outcome.archived_count,
            outcome.externalized_count,
            outcome.broken_files_dropped,
        ),
    )


def main() -> None:
    run_builtin_chop("notification_store_compact")


if __name__ == "__main__":
    main()
