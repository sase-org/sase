"""Validated filter state for the Artifacts Commits timeline."""

from __future__ import annotations

from dataclasses import dataclass

from sase.vcs_log.models import CommitFilters


@dataclass(frozen=True)
class CommitLogFilterValues:
    """Validated values shared by the commits pane and its editor modal."""

    authors: tuple[str, ...] = ()
    since_text: str = ""
    until_text: str = ""
    since: int | None = None
    until: int | None = None
    repos: tuple[str, ...] = ()
    limit: int = 40

    def backend_filters(self) -> CommitFilters:
        """Return the provider-neutral filter record used by ``run_vcs_log``."""
        return CommitFilters(
            since=self.since,
            until=self.until,
            authors=self.authors,
        )


__all__ = ["CommitLogFilterValues"]
