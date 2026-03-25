"""Collector functions that scan sase data sources for files matching a date range."""

import json
import re
from datetime import datetime
from pathlib import Path

from sase.core.time import get_timezone


# ---------------------------------------------------------------------------
# Timestamp extraction helpers
# ---------------------------------------------------------------------------

_TS_SUFFIX_RE = re.compile(r"-(\d{6}_\d{6})\.\w+$")
"""Matches ``-YYmmdd_HHMMSS.ext`` at end of a filename."""

_ARTIFACTS_TS_RE = re.compile(r"^(\d{14})$")
"""Matches ``YYYYmmddHHMMSS`` directory names used for artifacts."""


def _ts_from_filename_suffix(name: str) -> datetime | None:
    """Extract timestamp from a filename ending in ``-YYmmdd_HHMMSS.ext``."""
    m = _TS_SUFFIX_RE.search(name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%y%m%d_%H%M%S").replace(
            tzinfo=get_timezone()
        )
    except ValueError:
        return None


def _ts_from_artifacts_dir(name: str) -> datetime | None:
    """Extract timestamp from a ``YYYYmmddHHMMSS`` artifacts directory name."""
    m = _ARTIFACTS_TS_RE.match(name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(
            tzinfo=get_timezone()
        )
    except ValueError:
        return None


def _ts_from_mtime(path: Path) -> datetime:
    """Get a timezone-aware datetime from a file's mtime."""
    return datetime.fromtimestamp(path.stat().st_mtime, tz=get_timezone())


def _in_range(ts: datetime, start: datetime, end: datetime) -> bool:
    return start <= ts <= end


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------


def _collect_by_filename_suffix(
    directory: str, start: datetime, end: datetime, glob: str = "*"
) -> list[Path]:
    """Collect files whose filename contains a ``-YYmmdd_HHMMSS`` timestamp in range."""
    d = Path(directory).expanduser()
    if not d.is_dir():
        return []
    results: list[Path] = []
    for p in d.glob(glob):
        if not p.is_file():
            continue
        ts = _ts_from_filename_suffix(p.name)
        if ts and _in_range(ts, start, end):
            results.append(p)
    return sorted(results)


def _collect_by_mtime(
    directory: str, start: datetime, end: datetime, glob: str = "*"
) -> list[Path]:
    """Collect files whose mtime falls within the date range."""
    d = Path(directory).expanduser()
    if not d.is_dir():
        return []
    results: list[Path] = []
    for p in d.glob(glob):
        if not p.is_file():
            continue
        ts = _ts_from_mtime(p)
        if _in_range(ts, start, end):
            results.append(p)
    return sorted(results)


def collect_chats(start: datetime, end: datetime) -> list[Path]:
    return _collect_by_filename_suffix("~/.sase/chats", start, end, "*.md")


def collect_hooks(start: datetime, end: datetime) -> list[Path]:
    return _collect_by_filename_suffix("~/.sase/hooks", start, end, "*.txt")


def collect_workflows(start: datetime, end: datetime) -> list[Path]:
    return _collect_by_filename_suffix("~/.sase/workflows", start, end, "*.txt")


def collect_diffs(start: datetime, end: datetime) -> list[Path]:
    return _collect_by_mtime("~/.sase/diffs", start, end, "*.diff")


def collect_artifacts(start: datetime, end: datetime) -> list[Path]:
    """Collect artifact directories whose ``YYYYmmddHHMMSS`` name is in range."""
    projects_dir = Path("~/.sase/projects").expanduser()
    if not projects_dir.is_dir():
        return []
    results: list[Path] = []
    for project_dir in projects_dir.iterdir():
        artifacts_root = project_dir / "artifacts"
        if not artifacts_root.is_dir():
            continue
        for workflow_dir in artifacts_root.iterdir():
            if not workflow_dir.is_dir():
                continue
            for ts_dir in workflow_dir.iterdir():
                if not ts_dir.is_dir():
                    continue
                ts = _ts_from_artifacts_dir(ts_dir.name)
                if ts and _in_range(ts, start, end):
                    results.append(ts_dir)
    return sorted(results)


def collect_notifications(start: datetime, end: datetime) -> list[str]:
    """Return filtered JSONL lines from notifications.jsonl whose timestamp is in range."""
    return _collect_jsonl_by_iso_timestamp(
        "~/.sase/notifications/notifications.jsonl", start, end
    )


def collect_checks(start: datetime, end: datetime) -> list[Path]:
    return _collect_by_mtime("~/.sase/checks", start, end)


def collect_plans(start: datetime, end: datetime) -> list[Path]:
    return _collect_by_mtime("~/.sase/plan_approval", start, end)


def collect_questions(start: datetime, end: datetime) -> list[Path]:
    return _collect_by_mtime("~/.sase/user_question", start, end)


def _collect_jsonl_by_timestamp(path: str, start: datetime, end: datetime) -> list[str]:
    """Filter JSONL lines by their ``timestamp`` field (``YYmmdd_HHMMSS`` format)."""
    p = Path(path).expanduser()
    if not p.is_file():
        return []
    lines: list[str] = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts_str = data.get("timestamp", "")
        try:
            ts = datetime.strptime(ts_str, "%y%m%d_%H%M%S").replace(
                tzinfo=get_timezone()
            )
        except (ValueError, TypeError):
            continue
        if _in_range(ts, start, end):
            lines.append(line)
    return lines


def _collect_jsonl_by_iso_timestamp(
    path: str, start: datetime, end: datetime
) -> list[str]:
    """Filter JSONL lines by their ``timestamp`` field (ISO 8601 format)."""
    p = Path(path).expanduser()
    if not p.is_file():
        return []
    lines: list[str] = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts_str = data.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=get_timezone())
        except (ValueError, TypeError):
            continue
        if _in_range(ts, start, end):
            lines.append(line)
    return lines


def collect_comments(start: datetime, end: datetime) -> list[Path]:
    return _collect_by_filename_suffix("~/.sase/comments", start, end, "*.json")


def collect_mentors(start: datetime, end: datetime) -> list[Path]:
    return _collect_by_mtime("~/.sase/mentors", start, end, "*.json")


def collect_archived_diffs(start: datetime, end: datetime) -> list[Path]:
    return _collect_by_mtime("~/.sase/archived", start, end, "*.diff")


def collect_reverted_diffs(start: datetime, end: datetime) -> list[Path]:
    return _collect_by_mtime("~/.sase/reverted", start, end, "*.diff")


def collect_saved_plans(start: datetime, end: datetime) -> list[Path]:
    return _collect_by_mtime("~/.sase/plans", start, end)


def collect_axe_state(start: datetime, end: datetime) -> list[tuple[str, Path]]:
    """Collect axe lumberjack state files whose mtime falls within the date range.

    Returns a list of (lumberjack_name, file_path) tuples so the pack builder
    can preserve the per-lumberjack directory structure.
    """
    jacks_dir = Path("~/.sase/axe/lumberjacks").expanduser()
    if not jacks_dir.is_dir():
        return []
    results: list[tuple[str, Path]] = []
    for jack_dir in sorted(jacks_dir.iterdir()):
        if not jack_dir.is_dir():
            continue
        name = jack_dir.name
        # Collect state JSON files directly in the lumberjack dir
        for p in jack_dir.glob("*.json"):
            if p.is_file() and _in_range(_ts_from_mtime(p), start, end):
                results.append((name, p))
        # Collect output log
        log_file = jack_dir / "logs" / "output.log"
        if log_file.is_file() and _in_range(_ts_from_mtime(log_file), start, end):
            results.append((name, log_file))
    return results


def collect_run_log(start: datetime, end: datetime) -> list[str]:
    return _collect_jsonl_by_timestamp("~/.sase/logs/runs.jsonl", start, end)


def collect_event_log(start: datetime, end: datetime) -> list[str]:
    return _collect_jsonl_by_timestamp("~/.sase/logs/events.jsonl", start, end)


def collect_commit_stop_hook_log(start: datetime, end: datetime) -> list[str]:
    return _collect_jsonl_by_iso_timestamp("~/.sase_commit_stop_hook.jsonl", start, end)


def collect_git_commit_log(start: datetime, end: datetime) -> list[str]:
    return _collect_jsonl_by_iso_timestamp("~/.sase_git_commit.jsonl", start, end)
