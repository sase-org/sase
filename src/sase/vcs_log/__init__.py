"""Repo resolution + collection service for ``sase vcs log``.

A SASE project is a constellation of primary, linked, and sidecar repos.
This package resolves that repo set for the current workspace, collects a
commit log from each (through the provider-agnostic ``vcs_log`` hook), and
interleaves them into one chronological, cross-repository timeline via the
Rust core aggregator.

Public surface:

- :class:`LogRepo`, :class:`VcsLogResult` (``models``)
- :func:`resolve_log_repos`, :class:`ResolvedRepos` (``resolve``)
- :func:`collect_vcs_log`, :func:`run_vcs_log` (``collect``)
- the ``pretty`` / ``oneline`` / ``json`` renderers (``render``)
"""

from sase.vcs_log.collect import collect_vcs_log, run_vcs_log
from sase.vcs_log.models import CommitFilterSpec, LogRepo, LogRepoKind, VcsLogResult
from sase.vcs_log.resolve import ResolvedRepos, resolve_log_repos

__all__ = [
    "CommitFilterSpec",
    "LogRepo",
    "LogRepoKind",
    "ResolvedRepos",
    "VcsLogResult",
    "collect_vcs_log",
    "resolve_log_repos",
    "run_vcs_log",
]
