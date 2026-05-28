"""Build handlers for ``sase memory episodes``."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
from typing import Any

from sase.core.episode_facade import episode_wire_schema_version
from sase.core.episode_wire import (
    EpisodeBuildReportWire,
    EpisodeBuildRequestWire,
    EpisodeWire,
    episode_wire_to_json_dict,
)
from sase.memory.cli_episodes_common import (
    fail,
    print_json,
    project_from_args,
    validate_limit,
)
from sase.memory.episodes._build_progress import BuildProgress
from sase.memory.episodes.builder import build_episode
from sase.memory.episodes.collector import (
    EpisodeDraft,
    EpisodeSelector,
    collect_episode_draft,
)
from sase.memory.episodes.components import (
    EpisodeComponentPlan,
    build_episode_component_plans,
    collect_episode_draft_for_component_plan,
)
from sase.memory.episodes.index import project_episodes_dir
from sase.memory.episodes.render import render_lesson_markdown
from sase.memory.episodes.storage import EpisodeWriteResult, write_project_episode


def handle_episode_build(
    args: argparse.Namespace,
    *,
    projects_root: Path | str | None,
    repo_root: Path | str | None,
) -> None:
    validate_limit(args.limit, "limit")
    project = project_from_args(args)
    if getattr(args, "split", False):
        _handle_split_build(
            args,
            project=project,
            projects_root=projects_root,
            repo_root=repo_root,
        )
        return

    selector = _selector_from_args(args, project)
    is_json = bool(getattr(args, "json", False))
    is_quiet = bool(getattr(args, "quiet", False))
    progress = BuildProgress(enabled=not is_json and not is_quiet)
    selector_label = _selector_label(args)
    try:
        with progress:
            with progress.phase(
                f"Collecting episode draft (selector: {selector_label})"
            ):
                draft = collect_episode_draft(
                    selector,
                    projects_root=projects_root,
                    repo_root=repo_root if repo_root is not None else Path.cwd(),
                )
            progress.summary(
                f"Drafted episode with {len(draft.sources)} sources, "
                f"{len(draft.nodes)} nodes"
            )

            with progress.phase("Building episode"):
                episode = build_episode(draft)
            progress.summary(
                f"Built episode {episode.episode_id} ({len(episode.lessons)} lessons)"
            )

            with progress.phase("Rendering lesson markdown"):
                lesson_markdown = render_lesson_markdown(episode)
            progress.summary(f"Rendered lesson ({len(lesson_markdown)} bytes)")

            write_result = None
            with progress.phase("Writing episode files"):
                if not args.dry_run:
                    write_result = write_project_episode(
                        episode,
                        lesson_markdown=lesson_markdown,
                        projects_root=projects_root,
                    )
            if args.dry_run:
                progress.summary("Skipped (dry run)")
            else:
                progress.summary(
                    f"Wrote {episode.episode_id}/"
                    "{episode.json,lesson.md,sources.jsonl}"
                )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        fail(f"sase memory episodes build: {exc}")

    episode_dir = (
        write_result.episode_dir
        if write_result is not None
        else project_episodes_dir(episode.project, projects_root=projects_root)
        / episode.episode_id
    )
    schema_version = episode_wire_schema_version()
    build_request = EpisodeBuildRequestWire(
        schema_version=schema_version,
        project=episode.project,
        selector_kind=draft.selector_kind,
        selector_value=draft.selector_value,
        since=args.since,
        until=args.until,
        limit=args.limit,
        dry_run=bool(args.dry_run),
        force=bool(args.force),
        source_refs=list(episode.sources),
    )
    build_report = EpisodeBuildReportWire(
        schema_version=schema_version,
        project=episode.project,
        source_count=len(episode.sources),
        lesson_count=len(episode.lessons),
        episode_id=episode.episode_id,
        would_write=bool(args.dry_run),
        changed=write_result.changed if write_result is not None else False,
        warnings=list(draft.warnings),
    )
    payload = {
        "build_report": episode_wire_to_json_dict(build_report),
        "build_request": episode_wire_to_json_dict(build_request),
        "changed": write_result.changed if write_result is not None else False,
        "dry_run": bool(args.dry_run),
        "episode": episode_wire_to_json_dict(episode),
        "episode_dir": str(episode_dir.resolve(strict=False)),
        "episode_id": episode.episode_id,
        "force": bool(args.force),
        "lesson_count": len(episode.lessons),
        "project": episode.project,
        "schema_version": schema_version,
        "source_count": len(episode.sources),
        "title": episode.title,
        "warnings": draft.warnings,
        "would_write": bool(args.dry_run),
        "wrote": write_result is not None,
    }
    if getattr(args, "json", False):
        print_json(payload)
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


def _handle_split_build(
    args: argparse.Namespace,
    *,
    project: str,
    projects_root: Path | str | None,
    repo_root: Path | str | None,
) -> None:
    selector = _selector_from_args(args, project)
    is_json = bool(getattr(args, "json", False))
    is_quiet = bool(getattr(args, "quiet", False))
    progress = BuildProgress(enabled=not is_json and not is_quiet)
    selector_label = _selector_label(args)
    component_payloads: list[dict[str, Any]] = []
    try:
        with progress:
            with progress.phase(
                f"Planning episode components (selector: {selector_label})"
            ):
                plans = build_episode_component_plans(
                    selector,
                    projects_root=projects_root,
                    repo_root=repo_root if repo_root is not None else Path.cwd(),
                )
            progress.summary(f"Planned {len(plans)} component(s)")

            for index, plan in enumerate(plans, 1):
                component_label = _component_plan_label(plan, index, len(plans))
                with progress.phase(f"Collecting {component_label}"):
                    draft = collect_episode_draft_for_component_plan(
                        plan,
                        projects_root=projects_root,
                        repo_root=repo_root if repo_root is not None else Path.cwd(),
                    )
                progress.summary(
                    f"Drafted {component_label} with {len(draft.sources)} sources, "
                    f"{len(draft.nodes)} nodes"
                )

                with progress.phase(f"Building {component_label}"):
                    episode = build_episode(draft)
                progress.summary(
                    f"Built episode {episode.episode_id} "
                    f"({episode.importance_band}, {len(episode.sources)} sources)"
                )

                write_result = None
                with progress.phase(f"Writing {component_label}"):
                    if not args.dry_run:
                        write_result = write_project_episode(
                            episode,
                            projects_root=projects_root,
                        )
                if args.dry_run:
                    progress.summary("Skipped (dry run)")
                else:
                    assert write_result is not None
                    progress.summary(
                        f"Wrote {write_result.episode_id}/"
                        "{episode.json,sources.jsonl}"
                    )

                component_payloads.append(
                    _component_build_payload(
                        args,
                        plan=plan,
                        draft=draft,
                        episode=episode,
                        write_result=write_result,
                        projects_root=projects_root,
                    )
                )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        fail(f"sase memory episodes build --split: {exc}")

    schema_version = episode_wire_schema_version()
    payload = {
        "aggregate": False,
        "build_reports": [
            component["build_report"] for component in component_payloads
        ],
        "changed": any(component["changed"] for component in component_payloads),
        "component_count": len(component_payloads),
        "components": component_payloads,
        "dry_run": bool(args.dry_run),
        "force": bool(args.force),
        "project": project,
        "schema_version": schema_version,
        "split": True,
        "wrote": any(component["wrote"] for component in component_payloads),
        "would_write": bool(args.dry_run),
    }
    if is_json:
        print_json(payload)
        return

    if not component_payloads:
        print(f"No component episodes matched {selector_label} for project {project}.")
        return
    action = "Would build" if args.dry_run else "Built"
    print(
        f"{action} {len(component_payloads)} component episode(s) for project {project}"
    )
    for component in component_payloads:
        print("  " + _component_build_summary(component))


def _selector_from_args(args: argparse.Namespace, project: str) -> EpisodeSelector:
    return EpisodeSelector(
        project=project,
        agent=args.agent,
        artifact_dir=args.artifact_dir,
        changespec=args.changespec,
        chat=args.chat,
        since=args.since,
        until=args.until,
        limit=args.limit,
    )


def _component_plan_label(
    plan: EpisodeComponentPlan,
    index: int,
    total: int,
) -> str:
    return (
        f"component {index}/{total} ({plan.component_root_kind}:{plan.component_key})"
    )


def _component_build_payload(
    args: argparse.Namespace,
    *,
    plan: EpisodeComponentPlan,
    draft: EpisodeDraft,
    episode: EpisodeWire,
    write_result: EpisodeWriteResult | None,
    projects_root: Path | str | None,
) -> dict[str, Any]:
    stored_episode = (
        replace(episode, episode_id=write_result.episode_id)
        if write_result is not None and write_result.episode_id != episode.episode_id
        else episode
    )
    episode_dir = (
        write_result.episode_dir
        if write_result is not None
        else project_episodes_dir(stored_episode.project, projects_root=projects_root)
        / stored_episode.episode_id
    )
    schema_version = episode_wire_schema_version()
    warnings = sorted({*draft.warnings, *stored_episode.safety.warnings})
    build_request = EpisodeBuildRequestWire(
        schema_version=schema_version,
        project=stored_episode.project,
        selector_kind=draft.selector_kind,
        selector_value=draft.selector_value,
        since=args.since,
        until=args.until,
        limit=args.limit,
        dry_run=bool(args.dry_run),
        force=bool(args.force),
        source_refs=list(stored_episode.sources),
    )
    build_report = EpisodeBuildReportWire(
        schema_version=schema_version,
        project=stored_episode.project,
        source_count=len(stored_episode.sources),
        lesson_count=len(stored_episode.lessons),
        episode_id=stored_episode.episode_id,
        would_write=bool(args.dry_run),
        changed=write_result.changed if write_result is not None else False,
        warnings=warnings,
    )
    return {
        "build_report": episode_wire_to_json_dict(build_report),
        "build_request": episode_wire_to_json_dict(build_request),
        "changed": write_result.changed if write_result is not None else False,
        "component_key": plan.component_key,
        "component_plan": plan.to_json_dict(),
        "dry_run": bool(args.dry_run),
        "episode": episode_wire_to_json_dict(stored_episode),
        "episode_dir": str(episode_dir.resolve(strict=False)),
        "episode_id": stored_episode.episode_id,
        "force": bool(args.force),
        "importance_band": stored_episode.importance_band,
        "importance_score": stored_episode.importance_score,
        "lesson_count": len(stored_episode.lessons),
        "project": stored_episode.project,
        "schema_version": schema_version,
        "source_count": len(stored_episode.sources),
        "status": stored_episode.status,
        "title": stored_episode.title,
        "warnings": warnings,
        "would_write": bool(args.dry_run),
        "wrote": write_result is not None,
    }


def _component_build_summary(component: dict[str, Any]) -> str:
    details = [
        f"sources={component['source_count']}",
        f"band={component['importance_band']}",
        f"status={component['status']}",
    ]
    warnings = component.get("warnings") or []
    if warnings:
        details.append(f"warnings={len(warnings)}")
    return f"{component['episode_id']}  {component['title']}  " + " ".join(details)


def _selector_label(args: argparse.Namespace) -> str:
    if args.agent:
        return f"agent={args.agent}"
    if args.artifact_dir:
        return f"artifact_dir={args.artifact_dir}"
    if args.changespec:
        return f"changespec={args.changespec}"
    if args.chat:
        return f"chat={args.chat}"
    return "project_scan"
