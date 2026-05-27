"""CLI handler for ``sase memory episodes``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from sase.core.episode_wire import (
    EPISODE_WIRE_SCHEMA_VERSION,
    EpisodeStorageIndexRowWire,
    EpisodeVerifyReportWire,
    EpisodeWire,
    episode_wire_from_dict,
    episode_wire_to_json_dict,
)
from sase.main.init_memory.config import project_memory_name
from sase.memory.episodes.builder import build_episode
from sase.memory.episodes.collector import EpisodeSelector, collect_episode_draft
from sase.memory.episodes.index import (
    project_episodes_dir,
    read_episode_index,
)
from sase.memory.episodes.recall import recall_episode_rows
from sase.memory.episodes.render import render_lesson_markdown
from sase.memory.episodes.storage import (
    EPISODE_JSON_FILE_NAME,
    EPISODE_LESSON_FILE_NAME,
    EPISODE_SOURCES_FILE_NAME,
    write_project_episode,
)
from sase.memory.episodes.verify import verify_episode


def handle_memory_episodes_command(
    args: argparse.Namespace,
    *,
    projects_root: Path | str | None = None,
    repo_root: Path | str | None = None,
) -> None:
    """Dispatch ``sase memory episodes`` subcommands."""

    subcommand = getattr(args, "episodes_subcommand", None)
    if subcommand == "build":
        _handle_build(args, projects_root=projects_root, repo_root=repo_root)
        return
    if subcommand == "list":
        _handle_list(args, projects_root=projects_root)
        return
    if subcommand == "show":
        _handle_show(args, projects_root=projects_root)
        return
    if subcommand == "verify":
        _handle_verify(args, projects_root=projects_root)
        return
    if subcommand == "recall":
        _handle_recall(args, projects_root=projects_root)
        return

    print(
        "Usage: sase memory episodes {build,list,show,verify,recall}",
        file=sys.stderr,
    )
    sys.exit(1)


def _handle_build(
    args: argparse.Namespace,
    *,
    projects_root: Path | str | None,
    repo_root: Path | str | None,
) -> None:
    _validate_limit(args.limit, "limit")
    project = _project_from_args(args)
    selector = EpisodeSelector(
        project=project,
        agent=args.agent,
        artifact_dir=args.artifact_dir,
        changespec=args.changespec,
        chat=args.chat,
        since=args.since,
        until=args.until,
        limit=args.limit,
    )
    try:
        draft = collect_episode_draft(
            selector,
            projects_root=projects_root,
            repo_root=repo_root if repo_root is not None else Path.cwd(),
        )
        episode = build_episode(draft)
        lesson_markdown = render_lesson_markdown(episode)
        write_result = None
        if not args.dry_run:
            write_result = write_project_episode(
                episode,
                lesson_markdown=lesson_markdown,
                projects_root=projects_root,
            )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        _fail(f"sase memory episodes build: {exc}")

    episode_dir = (
        write_result.episode_dir
        if write_result is not None
        else project_episodes_dir(episode.project, projects_root=projects_root)
        / episode.episode_id
    )
    payload = {
        "changed": write_result.changed if write_result is not None else False,
        "dry_run": bool(args.dry_run),
        "episode": episode_wire_to_json_dict(episode),
        "episode_dir": str(episode_dir.resolve(strict=False)),
        "episode_id": episode.episode_id,
        "force": bool(args.force),
        "lesson_count": len(episode.lessons),
        "project": episode.project,
        "schema_version": EPISODE_WIRE_SCHEMA_VERSION,
        "source_count": len(episode.sources),
        "title": episode.title,
        "warnings": draft.warnings,
        "would_write": bool(args.dry_run),
        "wrote": write_result is not None,
    }
    if getattr(args, "json", False):
        _print_json(payload)
        return

    action = "Would build" if args.dry_run else "Built"
    print(
        f"{action} episode {episode.episode_id}: {episode.title} "
        f"({len(episode.sources)} sources, {len(episode.lessons)} lessons)"
    )
    print(f"project: {episode.project}")
    print(f"episode_dir: {episode_dir.resolve(strict=False)}")
    if draft.warnings:
        print(f"warnings: {len(draft.warnings)}")


def _handle_list(
    args: argparse.Namespace,
    *,
    projects_root: Path | str | None,
) -> None:
    _validate_limit(args.limit, "limit")
    project = _project_from_args(args)
    rows = read_episode_index(project, projects_root=projects_root)
    if args.limit is not None:
        rows = rows[: args.limit]

    if getattr(args, "json", False):
        _print_json(
            {
                "episodes": [episode_wire_to_json_dict(row) for row in rows],
                "project": project,
                "schema_version": EPISODE_WIRE_SCHEMA_VERSION,
            }
        )
        return

    if not rows:
        episodes_dir = project_episodes_dir(project, projects_root=projects_root)
        print(
            "No episodes stored yet under "
            f"{episodes_dir.resolve(strict=False)}. Build one with "
            "`sase memory episodes build -n <agent>`."
        )
        return

    for row in rows:
        details = _list_row_details(row)
        suffix = f"  {details}" if details else ""
        print(f"{row.episode_id}  {row.title}{suffix}")


def _handle_show(
    args: argparse.Namespace,
    *,
    projects_root: Path | str | None,
) -> None:
    project = _project_from_args(args)
    episode_dir = _resolve_episode_dir(project, args.episode_id, projects_root)
    fmt = "json" if getattr(args, "json", False) else args.format

    if fmt == "json":
        _print_file(episode_dir / EPISODE_JSON_FILE_NAME)
        return
    if fmt == "sources":
        sources_path = episode_dir / EPISODE_SOURCES_FILE_NAME
        if sources_path.exists():
            _print_file(sources_path)
            return
        episode = _load_episode(episode_dir)
        for source in sorted(episode.sources, key=lambda item: (item.kind, item.path)):
            print(json.dumps(episode_wire_to_json_dict(source), sort_keys=True))
        return
    if fmt == "timeline":
        episode = _load_episode(episode_dir)
        for event in sorted(
            episode.events,
            key=lambda item: (item.timestamp is None, item.timestamp or "", item.id),
        ):
            evidence = (
                " [evidence: " + ", ".join(sorted(event.evidence_ids)) + "]"
                if event.evidence_ids
                else ""
            )
            description = f" - {event.description}" if event.description else ""
            print(
                f"{event.timestamp or 'undated'} {event.title}{description}{evidence}"
            )
        return

    lesson_path = episode_dir / EPISODE_LESSON_FILE_NAME
    if lesson_path.exists():
        _print_file(lesson_path)
        return
    print(render_lesson_markdown(_load_episode(episode_dir)), end="")


def _handle_verify(
    args: argparse.Namespace,
    *,
    projects_root: Path | str | None,
) -> None:
    project = _project_from_args(args)
    if args.episode_id and args.all:
        _fail("sase memory episodes verify: specify an episode id or --all, not both")

    episode_dirs = (
        [_resolve_episode_dir(project, args.episode_id, projects_root)]
        if args.episode_id
        else _all_episode_dirs(project, projects_root)
    )
    reports = [_verify_episode_dir(path) for path in episode_dirs]

    if getattr(args, "json", False):
        _print_json(
            {
                "project": project,
                "reports": [episode_wire_to_json_dict(report) for report in reports],
                "schema_version": EPISODE_WIRE_SCHEMA_VERSION,
            }
        )
    elif not reports:
        print(f"No episodes stored for project {project}.")
    else:
        for report in reports:
            status = "ok" if report.ok else "drift"
            print(
                f"{report.episode_id}  {status}  "
                f"{report.ok_count} ok, {report.missing_count} missing, "
                f"{report.changed_count} changed"
            )
            for result in report.results:
                if result.status != "ok":
                    print(f"  {result.status}: {result.source_id} {result.path}")

    if any(not report.ok for report in reports):
        sys.exit(1)


def _handle_recall(
    args: argparse.Namespace,
    *,
    projects_root: Path | str | None,
) -> None:
    _validate_limit(args.limit, "limit")
    project = _project_from_args(args)
    try:
        matches = recall_episode_rows(
            read_episode_index(project, projects_root=projects_root),
            args.query,
            projects_root=projects_root,
            limit=args.limit,
        )
    except ValueError as exc:
        _fail(f"sase memory episodes recall: {exc}")

    if getattr(args, "json", False):
        _print_json(
            {
                "matches": [match.to_json_dict() for match in matches],
                "project": project,
                "query": args.query,
                "schema_version": EPISODE_WIRE_SCHEMA_VERSION,
            }
        )
        return

    if not matches:
        print(
            "No matching episodes. Try `list` to see what is stored, or "
            "`build` from a relevant agent."
        )
        return

    for match in matches:
        print(f"{match.episode_id}  score={match.score}  {match.title}")
        if match.lessons:
            for lesson in match.lessons:
                evidence = ", ".join(
                    f"{item.source_id}:{item.path}" if item.path else item.source_id
                    for item in lesson.evidence
                )
                suffix = f"  evidence={evidence}" if evidence else ""
                print(f"  - {lesson.lesson_id}: {lesson.text}{suffix}")
        elif match.excerpt:
            print(f"  {match.excerpt}")


def _project_from_args(args: argparse.Namespace) -> str:
    project = getattr(args, "project", None)
    if project is not None and project.strip():
        return project.strip()
    return project_memory_name(Path.cwd())


def _resolve_episode_dir(
    project: str,
    episode_id: str,
    projects_root: Path | str | None,
) -> Path:
    resolved_id = _resolve_episode_id(project, episode_id, projects_root)
    return project_episodes_dir(project, projects_root=projects_root) / resolved_id


def _resolve_episode_id(
    project: str,
    episode_id: str,
    projects_root: Path | str | None,
) -> str:
    requested = episode_id.strip()
    if not requested:
        _fail("sase memory episodes: episode id must not be empty")
    ids = _available_episode_ids(project, projects_root)
    exact = [item for item in ids if item == requested]
    if exact:
        return exact[0]
    prefix_matches = [item for item in ids if item.startswith(requested)]
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    if len(prefix_matches) > 1:
        _fail(
            "sase memory episodes: episode id prefix "
            f"`{requested}` is ambiguous: {', '.join(prefix_matches[:5])}"
        )
    available = ", ".join(ids[:5]) if ids else "list"
    _fail(
        f"sase memory episodes: No episode found for id `{requested}`. "
        f"Available ids: {available}."
    )
    raise AssertionError("unreachable")


def _available_episode_ids(
    project: str,
    projects_root: Path | str | None,
) -> list[str]:
    rows = read_episode_index(project, projects_root=projects_root)
    ids = {row.episode_id for row in rows}
    episodes_dir = project_episodes_dir(project, projects_root=projects_root)
    if episodes_dir.is_dir():
        for child in episodes_dir.iterdir():
            if child.is_dir() and (child / EPISODE_JSON_FILE_NAME).is_file():
                ids.add(child.name)
    return sorted(ids)


def _all_episode_dirs(
    project: str,
    projects_root: Path | str | None,
) -> list[Path]:
    return [
        project_episodes_dir(project, projects_root=projects_root) / episode_id
        for episode_id in _available_episode_ids(project, projects_root)
    ]


def _load_episode(episode_dir: Path) -> EpisodeWire:
    episode_path = episode_dir / EPISODE_JSON_FILE_NAME
    try:
        data = json.loads(episode_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _fail(f"sase memory episodes: missing episode.json under {episode_dir}")
    except (OSError, json.JSONDecodeError) as exc:
        _fail(f"sase memory episodes: failed to read {episode_path}: {exc}")
    try:
        return episode_wire_from_dict(data)
    except (KeyError, TypeError, ValueError) as exc:
        _fail(f"sase memory episodes: invalid episode.json under {episode_dir}: {exc}")
    raise AssertionError("unreachable")


def _verify_episode_dir(episode_dir: Path) -> EpisodeVerifyReportWire:
    return verify_episode(_load_episode(episode_dir))


def _print_file(path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        _fail(f"sase memory episodes: failed to read {path}: {exc}")
    print(text, end="" if text.endswith("\n") else "\n")


def _print_json(payload: Any) -> None:
    json.dump(payload, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")


def _list_row_details(row: EpisodeStorageIndexRowWire) -> str:
    parts: list[str] = []
    if row.root_agent_names:
        parts.append("agents=" + ",".join(row.root_agent_names))
    if row.changespec_name:
        parts.append(f"changespec={row.changespec_name}")
    if row.bead_ids:
        parts.append("beads=" + ",".join(row.bead_ids))
    if row.outcome:
        parts.append(f"outcome={row.outcome}")
    return " ".join(parts)


def _validate_limit(value: int | None, label: str) -> None:
    if value is not None and value < 1:
        _fail(f"sase memory episodes: {label} must be >= 1")


def _fail(message: str) -> None:
    print(message, file=sys.stderr)
    sys.exit(1)


__all__ = [
    "handle_memory_episodes_command",
]
