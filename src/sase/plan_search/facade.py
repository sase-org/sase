"""Python facade for the Rust-backed plan search.

The Rust core (``crates/sase_core``) owns plan discovery, filtering, and ranking;
this facade resolves the two source roots, decides which to scan from
``--source``, and forwards the filters across the ``plan_search`` binding.

Two sources are searched, SDD-store prioritized:

* **repo** — plans in the resolved SDD store, located via
  :func:`sase.sdd.store.resolve_sdd_dir`.
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
from sase.sdd.store import resolve_sdd_dir

SOURCE_ALL = "all"
SOURCE_REPO = "repo"
SOURCE_LOCAL = "local"
SOURCES = (SOURCE_ALL, SOURCE_REPO, SOURCE_LOCAL)

LOCAL_PLANS_SUBDIR = "plans"


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

    repo_path: Path | None = None
    repo_arg: str | None = None
    local_arg: str | None = None
    if source in (SOURCE_ALL, SOURCE_REPO):
        repo_path = _repo_sdd_root(repo_root, cwd=cwd)
        repo_arg = str(repo_path)
    if source in (SOURCE_ALL, SOURCE_LOCAL):
        local_arg = str(_local_plans_dir(local_dir))

    if repo_path is not None and _is_flat_plans_root(repo_path):
        payload = _search_flat_plans_root(
            binding,
            repo_path=repo_path,
            local_arg=local_arg,
            query=query,
            kinds=kinds,
            statuses=statuses,
            since=since,
            until=until,
            sort=sort,
            limit=limit,
        )
        return plan_search_matches_from_list(payload)

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
    if (path / "plans").is_dir():
        return False
    try:
        return any(
            child.is_dir() and len(child.name) == 6 and child.name.isdigit()
            for child in path.iterdir()
        )
    except OSError:
        return False


def _search_flat_plans_root(
    binding: Any,
    *,
    repo_path: Path,
    local_arg: str | None,
    query: str | None,
    kinds: Sequence[str] | None,
    statuses: Sequence[str] | None,
    since: str | None,
    until: str | None,
    sort: str | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    """Adapt a flat plans sidecar to the core's resolved-directory input."""

    repo_payload: list[dict[str, Any]] = binding(
        None,
        str(repo_path),
        query,
        None,
        _as_str_list(statuses),
        None,
        since,
        until,
        sort,
        None,
    )
    selected_kinds = {value.lower() for value in kinds} if kinds else None
    normalized_repo: list[dict[str, Any]] = []
    for item in repo_payload:
        plan = dict(item["plan"])
        frontmatter = dict(plan.get("frontmatter") or {})
        tier = str(frontmatter.get("tier") or "tale").lower()
        kind = tier if tier in {"tale", "epic"} else "tale"
        if selected_kinds is not None and kind not in selected_kinds:
            continue
        plan["source"] = SOURCE_REPO
        plan["kind"] = kind
        normalized = dict(item)
        normalized["plan"] = plan
        normalized["score"] = float(item.get("score", 0.0)) + 1.0
        normalized_repo.append(normalized)

    normalized_repo.extend(
        _search_repo_prompts(
            binding,
            repo_path=repo_path,
            query=query,
            statuses=statuses,
            since=since,
            until=until,
            sort=sort,
        )
        if _kind_selected(kinds, "prompt")
        else []
    )

    local_payload: list[dict[str, Any]] = []
    if local_arg is not None:
        local_payload = binding(
            None,
            local_arg,
            query,
            None,
            _as_str_list(statuses),
            None,
            since,
            until,
            sort,
            None,
        )
    merged = [*normalized_repo, *local_payload]
    _sort_wire_matches(merged, query=query, sort=sort)
    _apply_limit(merged, limit)
    return merged


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

    The Rust plan reader intentionally scans only plan/research artifacts. Prompt
    snapshots are one directory deeper (``<month>/prompts``), so the Python
    facade supplies each prompt directory as a local corpus, then restores repo
    identity before merging. Query matching, status/date filtering, scoring, and
    body/frontmatter parsing therefore remain core-owned.
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
    "SOURCES",
    "SOURCE_ALL",
    "SOURCE_LOCAL",
    "SOURCE_REPO",
    "search",
]
