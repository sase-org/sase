"""Git and artifact path helpers for commit finalization."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_ABSOLUTE_PATH_RE = re.compile(r"(?<![\w./~-])/(?:[^\s'\"`$;&|<>{}\[\]]+)")


def git_changed_files(repo_dir: str) -> list[str]:
    if not Path(repo_dir).is_dir():
        return []
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                repo_dir,
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    return _changed_files_from_git_status(result.stdout)


def observed_absolute_paths(artifact_root: Path) -> set[str]:
    paths: set[str] = set()
    for record in _read_tool_call_records(artifact_root):
        cwd = record.get("cwd")
        if isinstance(cwd, str):
            paths.update(_absolute_paths_from_text(cwd))
        for key in ("tool_input_summary", "tool_response_summary"):
            paths.update(_absolute_paths_from_value(record.get(key)))
    return paths


def _read_tool_call_records(artifact_root: Path) -> list[Mapping[str, Any]]:
    path = artifact_root / "tool_calls.jsonl"
    try:
        with open(path, encoding="utf-8") as f:
            records: list[Mapping[str, Any]] = []
            for line in f:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, Mapping):
                    records.append(record)
            return records
    except OSError:
        return []


def _absolute_paths_from_value(value: Any) -> set[str]:
    paths: set[str] = set()
    if isinstance(value, str):
        paths.update(_absolute_paths_from_text(value))
    elif isinstance(value, Mapping):
        for item in value.values():
            paths.update(_absolute_paths_from_value(item))
    elif isinstance(value, list):
        for item in value:
            paths.update(_absolute_paths_from_value(item))
    return paths


def _absolute_paths_from_text(text: str) -> set[str]:
    paths: set[str] = set()
    for match in _ABSOLUTE_PATH_RE.finditer(text):
        raw = match.group(0).rstrip(".,:;)]}'\"")
        if len(raw) > 1:
            paths.add(_normalize_path(raw))
    return paths


def agent_run_started_at(artifact_root: Path) -> float | None:
    meta_path = artifact_root / "agent_meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(meta, Mapping):
        return None
    raw = meta.get("run_started_at")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        started = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return started.timestamp()


def git_root_for_path(path: Path) -> str | None:
    current = path.expanduser()
    while not current.exists():
        parent = current.parent
        if parent == current:
            return None
        current = parent
    if current.is_file():
        current = current.parent
    try:
        result = subprocess.run(
            ["git", "-C", str(current), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    root = result.stdout.strip()
    return _normalize_path(root) if root else None


def git_remote_identities(repo_dir: str) -> set[str]:
    try:
        result = subprocess.run(
            ["git", "-C", repo_dir, "remote", "-v"],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except Exception:
        return set()
    if result.returncode != 0:
        return set()

    identities: set[str] = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        identity = _normalize_remote_identity(parts[1])
        if identity:
            identities.add(identity)
    return identities


def _normalize_remote_identity(url: str) -> str:
    value = url.strip()
    if not value:
        return ""
    if value.startswith("git@") and ":" in value:
        host, path = value.removeprefix("git@").split(":", 1)
        value = f"{host}/{path}"
    elif value.startswith("file://"):
        value = value.removeprefix("file://")
    elif "://" in value:
        parsed = urlparse(value)
        if parsed.hostname:
            host = parsed.hostname
            if parsed.port is not None:
                host = f"{host}:{parsed.port}"
            value = f"{host}{parsed.path}"

    if value.startswith("/") or value.startswith("~"):
        value = _normalize_path(value)
    return value.rstrip("/").removesuffix(".git")


def plausible_observed_changed_files(
    *,
    repo_root: str,
    changed_files: list[str],
    observed_paths: set[str],
    run_started_at: float | None,
) -> list[str]:
    plausible: list[str] = []
    for changed_file in changed_files:
        abs_path = _changed_file_abs_path(repo_root, changed_file)
        if abs_path in observed_paths or _mtime_after(abs_path, run_started_at):
            plausible.append(changed_file)
    return plausible


def _changed_file_abs_path(repo_root: str, changed_file: str) -> str:
    # Porcelain v1 rename lines are rendered as "old -> new"; the new path is
    # the current dirty file path when it exists in the worktree.
    path = changed_file.split(" -> ")[-1]
    return _normalize_path(str(Path(repo_root) / path))


def _mtime_after(path: str, threshold: float | None) -> bool:
    if threshold is None:
        return False
    try:
        return Path(path).stat().st_mtime >= threshold
    except OSError:
        return False


def _changed_files_from_git_status(status_text: str) -> list[str]:
    changed: list[str] = []
    for raw_line in status_text.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        changed.append(line[3:] if len(line) > 3 else line)
    return changed


def _normalize_path(path: str) -> str:
    return str(Path(path).expanduser().resolve(strict=False))
