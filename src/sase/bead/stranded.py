"""Load a stranded-work report for one project.

Callers wrap this on the UI thread's behalf: failures log a warning and
return an empty report instead of raising into ACE or doctor.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from time import time

from sase.bead.stranded_facts import collect_stranded_work_snapshot
from sase.core.stranded_work_facade import (
    STRANDED_UNKNOWN_RECORDS_UNAVAILABLE,
    STRANDED_WORK_WIRE_SCHEMA_VERSION,
    StrandedWorkReport,
    reduce_stranded_work,
)

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StrandedReport:
    """Reducer report plus bead titles and the collection timestamp.

    ``collection_failed`` is set when the collector raised; callers must not
    treat that empty report as a successful unchanged generation.
    ``stable_rebuild`` is true when bead/session projections were rematerialized
    rather than reused from a Rust-certified store identity.
    ``records_unavailable`` counts verdicts whose session records could not be
    read (``unknown``/``records_unavailable``); such a report is degraded and
    must never replace a complete generation in the warm cache.
    """

    report: StrandedWorkReport
    titles: Mapping[str, str]
    generated_at: float
    collection_failed: bool = False
    stable_rebuild: bool = True
    records_unavailable: int = 0

    @property
    def degraded(self) -> bool:
        """Return whether session-record gaps make this report degraded."""
        return self.records_unavailable > 0


def load_stranded_report(project: str, *, now: float | None = None) -> StrandedReport:
    """Collect facts and classify them. Failures yield an empty report."""
    moment = float(now) if now is not None else time()
    empty = StrandedReport(
        report=StrandedWorkReport(schema_version=STRANDED_WORK_WIRE_SCHEMA_VERSION),
        titles={},
        generated_at=moment,
        collection_failed=True,
        stable_rebuild=True,
    )
    try:
        facts, titles, rebuilt = collect_stranded_work_snapshot(project, now=moment)
        report = reduce_stranded_work(facts)
    except Exception:  # noqa: BLE001 - callers must never see collector errors.
        _LOG.warning(
            "stranded-work collector failed for project %s; returning empty report",
            project,
            exc_info=True,
        )
        return empty
    records_unavailable = sum(
        1
        for verdict in report.verdicts
        if verdict.state == "unknown"
        and verdict.reason == STRANDED_UNKNOWN_RECORDS_UNAVAILABLE
    )
    return StrandedReport(
        report=report,
        titles=titles,
        generated_at=moment,
        collection_failed=False,
        stable_rebuild=rebuilt,
        records_unavailable=records_unavailable,
    )


__all__ = ["StrandedReport", "load_stranded_report"]
