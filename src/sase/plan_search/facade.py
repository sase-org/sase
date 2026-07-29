"""Python facade for the Rust-backed document search.

The Rust core (``crates/sase_core``) owns document discovery, filtering, and
ranking; this facade resolves the repo document corpora and local archive,
decides which to scan from ``--source``, and forwards the filters across the
``plan_search`` binding.

Two sources are searched, SDD-store prioritized:

* **repo** — plans and configured document sidecars in the resolved SDD store.
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
from sase.sdd._paths import has_month_dirs
from sase.sdd.store import (
    PLANS_SIDECAR_ROLE,
    SDD_STORAGE_SIDECAR_REPOS,
    document_sidecar_roles,
    resolve_sdd_dir,
    resolve_sdd_store,
)

SOURCE_ALL = "all"
SOURCE_REPO = "repo"
SOURCE_LOCAL = "local"
SOURCES = (SOURCE_ALL, SOURCE_REPO, SOURCE_LOCAL)

LOCAL_PLANS_SUBDIR = "plans"
RESERVED_KINDS = ("tale", "epic", "prompt")

DocumentCorpus = tuple[str, str]


def _repo_sdd_root(
    override: Path | str | None = None, *, cwd: Path | None = None
) -> Path:
    """Resolve the SDD-store root for plan search.

    With no override, resolve from the current (or given) working directory;
    an override is run through :func:`resolve_sdd_root` so a project root is
    mapped to its ``sdd/`` subdir just like the bare resolution.
    """
    if override is not None:
        return resolve_sdd_root(str(override), cwd=cwd)
    base = Path.cwd() if cwd is None else cwd
    return resolve_sdd_dir(base, 1).resolve()


def _local_plans_dir(override: Path | str | None = None) -> Path:
    """Resolve the machine-local plan archive (``~/.sase/plans/``)."""
    if override is not None:
        return Path(override).expanduser()
    return sase_subdir(LOCAL_PLANS_SUBDIR)


def _repo_document_corpora(
    override: Path | str | None = None,
    *,
    cwd: Path | None = None,
) -> tuple[Path, list[DocumentCorpus] | None]:
    """Resolve the repo root and any explicit document corpora.

    Legacy in-tree/local stores retain the core's default ``sdd/plans`` and
    ``sdd/research`` scan. Split sidecar stores need explicit corpora because
    each role has its own repository root. An explicit flat plans-root override
    likewise becomes a single ``plans`` corpus, preserving the test and caller
    override contract without Python-side reclassification.
    """

    if override is not None:
        repo_path = _repo_sdd_root(override, cwd=cwd)
        corpora = (
            [(str(repo_path), PLANS_SIDECAR_ROLE)]
            if _is_flat_plans_root(repo_path)
            else None
        )
        return repo_path, corpora

    base = Path.cwd() if cwd is None else cwd
    store = resolve_sdd_store(base, 1)
    repo_path = store.sdd_dir.resolve()
    if store.storage != SDD_STORAGE_SIDECAR_REPOS:
        return repo_path, None

    roles = document_sidecar_roles(
        store.split_sidecar_roles(),
        include_plans=True,
    )
    corpora = [(str(store.kind_root(role).resolve()), role) for role in roles]
    return repo_path, corpora


def available_kinds(
    *,
    repo_root: Path | str | None = None,
    cwd: Path | None = None,
) -> tuple[str, ...]:
    """Return valid repo-kind filters for the current resolved project."""

    repo_path, corpora = _repo_document_corpora(repo_root, cwd=cwd)
    roles: tuple[str, ...]
    if corpora is None:
        # The core's legacy layout recognizes research as the one non-plans
        # document corpus. Keep the kind available even before its directory is
        # populated, matching the previous CLI contract.
        roles = (
            ("research",)
            if repo_root is None or not _is_flat_plans_root(repo_path)
            else ()
        )
    else:
        roles = tuple(role for _root, role in corpora if role != PLANS_SIDECAR_ROLE)
    return tuple(dict.fromkeys((*RESERVED_KINDS, *roles)))


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
    document_corpora: Sequence[tuple[Path | str, str]] | None = None,
) -> list[PlanSearchMatch]:
    """Search plans across the repo and local corpora and return ranked matches.

    ``query`` is optional: omit it (or pass blank) to browse. ``source`` selects
    which corpus to scan (``all``/``repo``/``local``). ``kinds`` narrows the repo
    corpus; ``statuses`` filters by frontmatter status; ``since``/``until`` bound
    the ``created_at`` date; ``sort`` is ``relevance``/``recent``/``title``;
    ``limit`` caps results (``0``/``None`` = unlimited). ``repo_root``/
    ``local_dir`` override root resolution (primarily for tests).
    ``document_corpora`` optionally supplies explicit ``(root, kind)`` repo
    corpora for callers that already resolved individual document-sidecar
    roles.
    """
    if source not in SOURCES:
        raise ValueError(
            f"invalid source {source!r}; expected one of {', '.join(SOURCES)}"
        )

    binding = require_rust_binding("plan_search")

    repo_path: Path | None = None
    repo_arg: str | None = None
    resolved_document_corpora: list[DocumentCorpus] | None = None
    local_arg: str | None = None
    if source in (SOURCE_ALL, SOURCE_REPO):
        if document_corpora is None:
            repo_path, resolved_document_corpora = _repo_document_corpora(
                repo_root,
                cwd=cwd,
            )
        else:
            resolved_document_corpora = [
                (str(Path(root).expanduser().resolve()), kind)
                for root, kind in document_corpora
            ]
            if repo_root is not None:
                repo_path = Path(repo_root).expanduser().resolve()
            elif resolved_document_corpora:
                repo_path = Path(resolved_document_corpora[0][0])
            else:
                repo_path = _repo_sdd_root(cwd=cwd)
        repo_arg = str(repo_path)
    if source in (SOURCE_ALL, SOURCE_LOCAL):
        local_arg = str(_local_plans_dir(local_dir))

    include_prompts = repo_path is not None and _kind_selected(kinds, "prompt")
    binding_limit = None if include_prompts else limit

    payload = binding(
        repo_arg,
        local_arg,
        query,
        _as_str_list(kinds),
        _as_str_list(statuses),
        None,  # `sources` filter expressed via root selection above
        since,
        until,
        sort,
        binding_limit,
        resolved_document_corpora,
    )
    if include_prompts:
        assert repo_path is not None
        payload.extend(
            _search_repo_prompts(
                binding,
                repo_path=repo_path,
                query=query,
                statuses=statuses,
                since=since,
                until=until,
                sort=sort,
            )
        )
        _sort_wire_matches(payload, query=query, sort=sort)
        _apply_limit(payload, limit)
    return plan_search_matches_from_list(payload)


def _is_flat_plans_root(path: Path) -> bool:
    if has_month_dirs(path / "plans"):
        return False
    return has_month_dirs(path)


def _search_repo_prompts(
    binding: Any,
    *,
    repo_path: Path,
    query: str | None,
    statuses: Sequence[str] | None,
    since: str | None,
    until: str | None,
    sort: str | None,
) -> list[dict[str, Any]]:
    """Search prompt directories through the core engine and relabel results.

    Prompt snapshots are one directory deeper (``<month>/prompts``), so the
    Python facade supplies each prompt directory as a local corpus, then
    restores repo identity before merging. Query matching, status/date
    filtering, scoring, and body/frontmatter parsing therefore remain core-owned.
    """
    normalized: list[dict[str, Any]] = []
    for prompt_dir in _repo_prompt_dirs(repo_path):
        prompt_payload: list[dict[str, Any]] = binding(
            None,
            str(prompt_dir),
            query,
            None,
            _as_str_list(statuses),
            None,
            since,
            until,
            sort,
            None,
        )
        for item in prompt_payload:
            plan = dict(item["plan"])
            prompt_path = Path(str(plan["path"]))
            try:
                relpath = prompt_path.relative_to(repo_path).as_posix()
            except ValueError:
                relpath = prompt_path.name
            plan["source"] = SOURCE_REPO
            plan["kind"] = "prompt"
            plan["relpath"] = relpath
            result = dict(item)
            result["plan"] = plan
            result["score"] = float(item.get("score", 0.0)) + 1.0
            normalized.append(result)
    return normalized


def _repo_prompt_dirs(repo_path: Path) -> tuple[Path, ...]:
    """Return canonical and tolerated legacy prompt roots without duplicates."""
    plans_root = repo_path / "plans"
    if not plans_root.is_dir():
        plans_root = repo_path

    roots: list[Path] = []
    if plans_root.is_dir():
        roots.extend(
            prompt_dir
            for prompt_dir in sorted(plans_root.glob("*/prompts"))
            if prompt_dir.is_dir()
        )
    roots.extend(
        root
        for dirname in ("prompts", "specs")
        if (root := repo_path / dirname).is_dir()
    )
    return tuple(dict.fromkeys(root.resolve() for root in roots))


def _kind_selected(kinds: Sequence[str] | None, kind: str) -> bool:
    return kinds is None or any(value.lower() == kind for value in kinds)


def _apply_limit(items: list[dict[str, Any]], limit: int | None) -> None:
    if limit is not None and limit > 0:
        del items[limit:]


def _sort_wire_matches(
    items: list[dict[str, Any]], *, query: str | None, sort: str | None
) -> None:
    mode = sort or ("relevance" if query and query.strip() else "recent")
    items.sort(
        key=lambda item: (
            0 if item["plan"].get("source") == SOURCE_REPO else 1,
            str(item["plan"].get("relpath", "")),
            str(item["plan"].get("source", "")),
        )
    )
    if mode == "title":
        items.sort(key=lambda item: str(item["plan"].get("title", "")).lower())
    else:
        items.sort(
            key=lambda item: str(item["plan"].get("created_at", "")),
            reverse=True,
        )
        if mode == "relevance":
            items.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)


def _as_str_list(values: Sequence[str] | None) -> list[str] | None:
    if values is None:
        return None
    return [str(value) for value in values]


__all__ = [
    "RESERVED_KINDS",
    "SOURCES",
    "SOURCE_ALL",
    "SOURCE_LOCAL",
    "SOURCE_REPO",
    "available_kinds",
    "search",
]
