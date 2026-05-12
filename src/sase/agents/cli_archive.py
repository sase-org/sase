"""Archive commands for dismissed agent bundles."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sase.ace.agent_query.archive_planner import (
    ArchiveQueryError,
    ArchiveQueryResult,
    archive_facet_counts,
    search_archive,
    select_archive_results,
)


def _archive_root() -> Path:
    from sase.ace import dismissed_agents

    return dismissed_agents._DISMISSED_BUNDLES_DIR


def handle_agents_archive(args: argparse.Namespace) -> None:
    """Dispatch ``sase agents archive`` subcommands."""

    sub = getattr(args, "archive_subcommand", None)
    if sub == "rebuild-index":
        from sase.ace.dismissed_agents import rebuild_dismissed_bundle_index

        indexed, skipped = rebuild_dismissed_bundle_index()
        print(f"Indexed {indexed} dismissed bundles; skipped {skipped} corrupt files.")
        sys.exit(0)

    if sub == "verify":
        from sase.ace.dismissed_agents import verify_dismissed_bundle_index

        result = verify_dismissed_bundle_index()
        print(json.dumps(result, indent=2, sort_keys=True))
        sys.exit(0 if result["ok"] else 1)

    if sub == "search":
        _handle_search(args)
        sys.exit(0)

    if sub == "show":
        _handle_show(args)
        sys.exit(0)

    if sub == "stats":
        _handle_stats(args)
        sys.exit(0)

    if sub == "revive":
        _handle_revive(args)
        sys.exit(0)

    print("Usage: sase agents archive {rebuild-index,revive,search,show,stats,verify}")
    sys.exit(1)


def _handle_search(args: argparse.Namespace) -> None:
    try:
        page = search_archive(
            _archive_root(),
            args.query,
            limit=max(0, int(args.limit)),
        )
    except ArchiveQueryError as exc:
        print(f"Archive query error: {exc}", file=sys.stderr)
        sys.exit(2)

    if args.json:
        print(
            json.dumps(
                {
                    "results": [_result_to_dict(row) for row in page.results],
                    "next_cursor": page.next_cursor,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    if not page.results:
        print("No archived agents matched.")
        return
    for row in page.results:
        print(_format_result_line(row))


def _handle_show(args: argparse.Namespace) -> None:
    try:
        rows = select_archive_results(
            _archive_root(),
            agent_id=args.agent_id,
            name=args.name,
            suffix=args.suffix,
            limit=2,
        )
    except ArchiveQueryError as exc:
        print(f"Archive show error: {exc}", file=sys.stderr)
        sys.exit(2)
    if not rows:
        print("No archived agent matched.", file=sys.stderr)
        sys.exit(2)
    if len(rows) > 1:
        print("Archive selector matched multiple agents.", file=sys.stderr)
        sys.exit(2)

    row = rows[0]
    try:
        bundle = _read_bundle(row.bundle_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Failed to read archived bundle: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(
            json.dumps(
                {"summary": _result_to_dict(row), "bundle": bundle},
                indent=2,
                sort_keys=True,
            )
        )
        return
    print(_format_result_line(row))
    print(f"bundle_path: {row.bundle_path}")
    for key in ("project_file", "artifacts_dir", "response_path", "error_message"):
        value = bundle.get(key)
        if value:
            print(f"{key}: {value}")


def _handle_stats(args: argparse.Namespace) -> None:
    facets = [part.strip() for part in args.by.split(",") if part.strip()]
    if not facets:
        print("No archive stat facets requested.", file=sys.stderr)
        sys.exit(2)

    try:
        result = {
            facet: archive_facet_counts(_archive_root(), args.query, facet=facet)
            for facet in facets
        }
    except ArchiveQueryError as exc:
        print(f"Archive stats error: {exc}", file=sys.stderr)
        sys.exit(2)

    if args.json:
        print(
            json.dumps(
                {"query": args.query, "facets": result},
                indent=2,
                sort_keys=True,
            )
        )
        return
    for facet in facets:
        print(f"{facet}:")
        counts = result[facet]
        if not counts:
            print("  (none)")
            continue
        for value, count in counts.items():
            label = value or "(empty)"
            print(f"  {label}: {count}")


def _handle_revive(args: argparse.Namespace) -> None:
    try:
        limit = 10000 if args.all else 2
        rows = search_archive(_archive_root(), args.query, limit=limit).results
    except ArchiveQueryError as exc:
        print(f"Archive revive query error: {exc}", file=sys.stderr)
        sys.exit(2)
    if not rows:
        print("No archived agents matched.", file=sys.stderr)
        sys.exit(2)
    if len(rows) > 1 and not args.all:
        print(
            "Archive revive query matched multiple agents; pass --all or narrow it.",
            file=sys.stderr,
        )
        sys.exit(2)

    try:
        restored_count, marked_count = _revive_archive_rows(rows)
    except (OSError, ValueError, TypeError) as exc:
        print(f"Failed to revive archived agent: {exc}", file=sys.stderr)
        sys.exit(1)

    payload = {
        "revived": [_result_to_dict(row) for row in rows],
        "restored_agents": restored_count,
        "marked_bundles": marked_count,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(
        f"Revived {restored_count} archived agent"
        f"{'s' if restored_count != 1 else ''}; marked {marked_count} bundle"
        f"{'s' if marked_count != 1 else ''}."
    )


def _revive_archive_rows(rows: list[ArchiveQueryResult]) -> tuple[int, int]:
    from sase.ace.dismissed_agents import (
        load_dismissed_agents,
        load_dismissed_bundles,
        mark_bundles_revived_by_suffixes,
        save_dismissed_agents,
    )
    from sase.ace.tui.actions.agents._revive_artifacts import ArtifactRestorationMixin

    suffixes = {row.raw_suffix for row in rows if row.raw_suffix}
    agents = load_dismissed_bundles(suffixes)
    if not agents:
        raise ValueError("selected archive bundle rows could not be hydrated")

    class _Restorer(ArtifactRestorationMixin):
        pass

    restorer = _Restorer()
    restored: set[tuple[Any, str, str | None]] = set()
    parents = [agent for agent in agents if not agent.is_workflow_child]
    children = [agent for agent in agents if agent.is_workflow_child]
    for agent in parents:
        restorer._restore_agent_artifacts(agent)
        restored.add(agent.identity)
        for child in children:
            if _is_child_agent_of(child, agent):
                restorer._restore_agent_artifacts(
                    child,
                    parent_artifacts_dir=agent.artifacts_dir,
                )
                restored.add(child.identity)
    for child in children:
        if child.identity in restored:
            continue
        restorer._restore_agent_artifacts(child)
        restored.add(child.identity)

    revived_suffixes = {agent.raw_suffix for agent in agents if agent.raw_suffix}
    dismissed = load_dismissed_agents()
    next_dismissed = {
        identity
        for identity in dismissed
        if identity[2] is None or identity[2] not in revived_suffixes
    }
    if next_dismissed != dismissed:
        save_dismissed_agents(next_dismissed)

    marked_count = mark_bundles_revived_by_suffixes(revived_suffixes)
    return len(restored), marked_count


def _is_child_agent_of(child: Any, parent: Any) -> bool:
    if (
        child.retry_of_timestamp
        and parent.raw_suffix
        and child.retry_of_timestamp == parent.raw_suffix
    ):
        return True
    if not child.is_workflow_child or child.parent_timestamp != parent.raw_suffix:
        return False
    return child.parent_workflow is None or child.parent_workflow == parent.workflow


def _result_to_dict(row: ArchiveQueryResult) -> dict[str, Any]:
    return {
        "agent_id": row.agent_id,
        "raw_suffix": row.raw_suffix,
        "bundle_path": row.bundle_path,
        "cl_name": row.cl_name,
        "agent_name": row.agent_name,
        "status": row.status,
        "start_time": row.start_time,
        "dismissed_at": row.dismissed_at,
        "revived_at": row.revived_at,
        "project_name": row.project_name,
        "model": row.model,
        "runtime": row.runtime,
        "llm_provider": row.llm_provider,
        "step_index": row.step_index,
        "step_name": row.step_name,
        "step_type": row.step_type,
        "retry_attempt": row.retry_attempt,
        "is_workflow_child": row.is_workflow_child,
    }


def _format_result_line(row: ArchiveQueryResult) -> str:
    name = row.agent_name or row.cl_name
    project = row.project_name or "-"
    model = row.model or "-"
    runtime = row.runtime or "-"
    dismissed = row.dismissed_at or row.start_time or "-"
    return (
        f"{row.agent_id[:12]} {row.status:<8} {name} "
        f"project={project} model={model} runtime={runtime} "
        f"suffix={row.raw_suffix} dismissed={dismissed}"
    )


def _read_bundle(bundle_path: str) -> dict[str, Any]:
    data = json.loads(Path(bundle_path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("bundle JSON must be an object")
    return data
