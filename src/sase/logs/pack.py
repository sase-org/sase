"""Build a self-contained log pack for a given date range."""

import json
import shutil
from datetime import datetime
from pathlib import Path

from sase.sase_utils import EASTERN_TZ

from sase.logs.collectors import (
    collect_artifacts,
    collect_chats,
    collect_checks,
    collect_diffs,
    collect_event_log,
    collect_hooks,
    collect_notifications,
    collect_plans,
    collect_questions,
    collect_run_log,
    collect_workflows,
)


def build_pack(start: datetime, end: datetime, range_spec: str) -> str:
    """Run all collectors and build a timestamped pack directory.

    Returns the absolute path to the pack directory.
    """
    now = datetime.now(EASTERN_TZ)
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
