#!/usr/bin/env python3
"""Error digest notification chop script."""

import logging

from sase.axe.error_digest import prune_old_error_digests
from sase.axe.state import (
    mark_error_digest_sent,
    rotate_error_interval,
)
from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.notifications.senders import notify_axe_error_digest

_logger = logging.getLogger(__name__)


@builtin_chop("error_digest")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    pending = rotate_error_interval()
    notified = 0
    errors_total = 0
    causes = 0
    newest = None
    for record in pending:
        notify_axe_error_digest(record=record)
        interval_id = record.get("interval_id")
        if isinstance(interval_id, str) and interval_id:
            mark_error_digest_sent(interval_id)
        end = record.get("interval_end")
        if isinstance(end, str) and end:
            newest = end
        notified += 1
        errors_total += int(record.get("total") or 0)
        groups = record.get("groups")
        if isinstance(groups, list):
            causes += len(groups)
    pruned = 0
    try:
        pruned = prune_old_error_digests()
    except Exception as exc:  # noqa: BLE001 - prune is best-effort
        _logger.warning("Failed to prune old error digests: %s", exc)
    return runtime.emit_summary(
        {
            "errors_total": errors_total,
            "causes": causes,
            "notified": notified,
            "pruned": pruned,
            "newest": newest,
        },
        reason=None if pending or pruned else "no_recent_errors",
    )


def main() -> None:
    run_builtin_chop("error_digest")


if __name__ == "__main__":
    main()
