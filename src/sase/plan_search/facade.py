"""Python facade for the Rust-backed plan search.

The Rust core (``crates/sase_core``) owns plan discovery, filtering, and ranking;
this facade resolves the two source roots, decides which to scan from
``--source``, and forwards the filters across the ``plan_search`` binding.

Two sources are searched, repo prioritized:

* **repo** — committed ``sdd/`` plans, located via
  :func:`sase.sdd.links.resolve_sdd_root`.
* **local** — the machine-local archive under ``~/.sase/plans/`` (resolved via
  :func:`sase.core.paths.sase_subdir`).

``--source`` is expressed by *which roots are passed* to Rust: ``repo`` passes
only the repo root, ``local`` passes only the local dir, ``all`` passes both.
Passing ``None`` for a root simply skips that corpus, so the Rust ``sources``
filter is left unused here.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sase.core.paths import sase_subdir
from sase.core.rust import require_rust_binding
from sase.plan_search.model import PlanSearchMatch
from sase.plan_search.wire import plan_search_matches_from_list
from sase.sdd.links import resolve_sdd_root

SOURCE_ALL = "all"
SOURCE_REPO = "repo"
SOURCE_LOCAL = "local"
SOURCES = (SOURCE_ALL, SOURCE_REPO, SOURCE_LOCAL)

LOCAL_PLANS_SUBDIR = "plans"


def _repo_sdd_root(
    override: Path | str | None = None, *, cwd: Path | None = None
) -> Path:
    """Resolve the repo ``sdd/`` root for plan search.

    With no override, resolve from the current (or given) working directory;
    an override is run through :func:`resolve_sdd_root` so a project root is
    mapped to its ``sdd/`` subdir just like the bare resolution.
    """
    if override is not None:
        return resolve_sdd_root(str(override), cwd=cwd)
    return resolve_sdd_root(cwd=cwd)


def _local_plans_dir(override: Path | str | None = None) -> Path:
    """Resolve the machine-local plan archive (``~/.sase/plans/``)."""
    if override is not None:
        return Path(override).expanduser()
    return sase_subdir(LOCAL_PLANS_SUBDIR)


def search(
    query: str | None = None,
    *,
    kinds: Sequence[str] | None = None,
    statuses: Sequence[str] | None = None,
    source: str = SOURCE_ALL,
    since: str | None = None,
    until: str | None = None,
    sort: str | None = None,
    limit: int | None = None,
    repo_root: Path | str | None = None,
    local_dir: Path | str | None = None,
    cwd: Path | None = None,
) -> list[PlanSearchMatch]:
    """Search plans across the repo and local corpora and return ranked matches.

    ``query`` is optional: omit it (or pass blank) to browse. ``source`` selects
    which corpus to scan (``all``/``repo``/``local``). ``kinds`` narrows the repo
    corpus; ``statuses`` filters by frontmatter status; ``since``/``until`` bound
    the ``created_at`` date; ``sort`` is ``relevance``/``recent``/``title``;
    ``limit`` caps results (``0``/``None`` = unlimited). ``repo_root``/
    ``local_dir`` override root resolution (primarily for tests).
    """
    if source not in SOURCES:
        raise ValueError(
            f"invalid source {source!r}; expected one of {', '.join(SOURCES)}"
        )

    binding = require_rust_binding("plan_search")

    repo_arg: str | None = None
    local_arg: str | None = None
    if source in (SOURCE_ALL, SOURCE_REPO):
        repo_arg = str(_repo_sdd_root(repo_root, cwd=cwd))
    if source in (SOURCE_ALL, SOURCE_LOCAL):
        local_arg = str(_local_plans_dir(local_dir))

    payload: list[dict[str, Any]] = binding(
        repo_arg,
        local_arg,
        query,
        _as_str_list(kinds),
        _as_str_list(statuses),
        None,  # `sources` filter expressed via root selection above
        since,
        until,
        sort,
        limit,
    )
    return plan_search_matches_from_list(payload)


def _as_str_list(values: Sequence[str] | None) -> list[str] | None:
    if values is None:
        return None
    return [str(value) for value in values]


__all__ = [
    "SOURCES",
    "SOURCE_ALL",
    "SOURCE_LOCAL",
    "SOURCE_REPO",
    "search",
]
