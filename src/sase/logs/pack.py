"""Build a self-contained log pack for a given date range."""

import json
import shutil
from datetime import datetime
from pathlib import Path

from sase.core.time import get_timezone

from sase.logs.collectors import (
    collect_archived_diffs,
    collect_artifacts,
    collect_axe_state,
    collect_chats,
    collect_checks,
    collect_comments,
    collect_commit_stop_hook_log,
    collect_diffs,
    collect_event_log,
    collect_git_commit_log,
    collect_hooks,
    collect_mentors,
    collect_notifications,
    collect_plans,
    collect_questions,
    collect_reverted_diffs,
    collect_run_log,
    collect_saved_plans,
    collect_workflows,
)


def build_pack(start: datetime, end: datetime, range_spec: str) -> str:
    """Run all collectors and build a timestamped pack directory.

    Returns the absolute path to the pack directory.
    """
    now = datetime.now(get_timezone())
    pack_name = now.strftime("%y%m%d_%H%M%S")
    pack_dir = Path("~/.sase/logs/pack").expanduser() / pack_name
    pack_dir.mkdir(parents=True, exist_ok=True)

    file_count = 0

    # -- file-based collectors --
    collector_map: dict[str, list[Path]] = {
        "chats": collect_chats(start, end),
        "hooks": collect_hooks(start, end),
        "workflows": collect_workflows(start, end),
        "diffs": collect_diffs(start, end),
        "checks": collect_checks(start, end),
        "plans": collect_plans(start, end),
        "questions": collect_questions(start, end),
        "comments": collect_comments(start, end),
        "mentors": collect_mentors(start, end),
        "archived": collect_archived_diffs(start, end),
        "reverted": collect_reverted_diffs(start, end),
        "saved_plans": collect_saved_plans(start, end),
    }

    for subdir, files in collector_map.items():
        if not files:
            continue
        dest = pack_dir / subdir
        dest.mkdir(exist_ok=True)
        for src_path in files:
            shutil.copy2(src_path, dest / src_path.name)
            file_count += 1

    # -- artifacts (copy entire directories) --
    artifact_dirs = collect_artifacts(start, end)
    if artifact_dirs:
        artifacts_dest = pack_dir / "artifacts"
        artifacts_dest.mkdir(exist_ok=True)
        for art_dir in artifact_dirs:
            # Preserve project/workflow/timestamp hierarchy
            rel = art_dir.relative_to(Path("~/.sase/projects").expanduser())
            dest = artifacts_dest / rel
            shutil.copytree(art_dir, dest, dirs_exist_ok=True)
            file_count += 1

    # -- axe lumberjack state (preserve per-lumberjack structure) --
    axe_files = collect_axe_state(start, end)
    if axe_files:
        for jack_name, src_path in axe_files:
            rel = src_path.relative_to(
                Path("~/.sase/axe/lumberjacks").expanduser() / jack_name
            )
            dest = pack_dir / "axe" / jack_name / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dest)
            file_count += 1

    # -- JSONL-based collectors --
    notifications = collect_notifications(start, end)
    if notifications:
        (pack_dir / "notifications.jsonl").write_text("\n".join(notifications) + "\n")
        file_count += len(notifications)

    run_lines = collect_run_log(start, end)
    if run_lines:
        (pack_dir / "runs.jsonl").write_text("\n".join(run_lines) + "\n")
        file_count += len(run_lines)

    event_lines = collect_event_log(start, end)
    if event_lines:
        (pack_dir / "events.jsonl").write_text("\n".join(event_lines) + "\n")
        file_count += len(event_lines)

    commit_stop_lines = collect_commit_stop_hook_log(start, end)
    if commit_stop_lines:
        (pack_dir / "commit_stop_hook.jsonl").write_text(
            "\n".join(commit_stop_lines) + "\n"
        )
        file_count += len(commit_stop_lines)

    git_commit_lines = collect_git_commit_log(start, end)
    if git_commit_lines:
        (pack_dir / "git_commit.jsonl").write_text("\n".join(git_commit_lines) + "\n")
        file_count += len(git_commit_lines)

    # -- manifest --
    manifest = {
        "created": now.isoformat(),
        "range_start": start.isoformat(),
        "range_end": end.isoformat(),
        "range_spec": range_spec,
        "file_count": file_count,
        "pack_dir": str(pack_dir),
    }
    (pack_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    return str(pack_dir)
