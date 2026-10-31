"""Name and aggregate queries for the wait-dependency artifact index."""

from __future__ import annotations

from ._index_candidate_queries import WaitDependencyCandidateQueries
from ._index_member_dir_queries import WaitDependencyMemberDirQueries


class WaitDependencyIndexQueries(
    WaitDependencyMemberDirQueries,
    WaitDependencyCandidateQueries,
):
    """Read-side operations shared by :class:`WaitDependencyIndex`."""
