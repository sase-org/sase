"""Historical auto-name migration for permanent agent names."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.agent.names._common import is_dismissed_prefixed
from sase.core.agent_artifact_index_lifecycle import (
    sync_dismissed_agent_artifact_index,
    upsert_agent_artifact_index_artifacts,
)

MIGRATION_SCHEMA_VERSION = 1
MIGRATION_MARKER_FILENAME = "agent_name_auto_migration.json"

_OLD_AUTO_NAME_RE = re.compile(r"^[a-z]+(?:\.(?:[a-z]+|\d+|r\d+))*$")
_ARTIFACT_SUFFIX_RE = re.compile(r"^(\d{8})")
_RUNNER_TIMESTAMP_RE = re.compile(r"^(\d{6})_")
_JSON_NAME_KEYS = {"name", "workflow_name", "agent_name"}
_JSON_REF_KEYS = {"wait_for", "waiting_for"}
_INDEXED_ARTIFACT_MARKER_NAMES = {"agent_meta.json", "done.json", "waiting.json"}
_NOTIFICATION_ACTION_NAME_KEYS = {
    "agent_name",
    "parent_agent_name",
    "source_agent_name",
    "target_agent_name",
    "workflow_name",
}


@dataclass(frozen=True)
class _AgentAutoNameMigrationResult:
    """Summary of one historical auto-name migration run."""

    changed: bool
    migrated_names: dict[str, str]
    files_changed: tuple[str, ...]
    skipped_by_marker: bool = False


def run_historical_auto_name_migration(
    *,
    force: bool = False,
) -> _AgentAutoNameMigrationResult:
    """Prefix legacy auto-generated names with ``YYmmdd.`` and rewrite refs."""
    marker_path = _migration_marker_path()
    if not force and _marker_is_complete(marker_path):
        return _AgentAutoNameMigrationResult(
            changed=False,
            migrated_names={},
            files_changed=(),
            skipped_by_marker=True,
        )

    mapping = _collect_legacy_auto_name_mapping()
    changed_files: set[Path] = set()
    if mapping:
        artifact_marker_files = _rewrite_artifact_json_files(mapping)
        changed_files.update(artifact_marker_files)
        artifact_index_dirs = _indexed_artifact_dirs_for_changed_files(
            artifact_marker_files
        )
        if artifact_index_dirs:
            upsert_agent_artifact_index_artifacts(artifact_index_dirs)

        dismissed_bundle_files = _rewrite_dismissed_bundle_files(mapping)
        changed_files.update(dismissed_bundle_files)
        if dismissed_bundle_files:
            sync_dismissed_agent_artifact_index(force=True)

        changed_files.update(_rewrite_prompt_artifact_files(mapping))
        changed_files.update(_rewrite_prompt_history(mapping))
        changed_files.update(_rewrite_notifications(mapping))
        if os.environ.get("SASE_AGENT_NAME") in mapping:
            os.environ["SASE_AGENT_NAME"] = mapping[os.environ["SASE_AGENT_NAME"]]

    _write_marker(marker_path, mapping)

    from sase.agent.names._registry import rebuild_name_registry

    rebuild_name_registry()
    return _AgentAutoNameMigrationResult(
        changed=bool(changed_files),
        migrated_names=dict(sorted(mapping.items())),
        files_changed=tuple(str(path) for path in sorted(changed_files)),
    )


def ensure_historical_auto_name_migration() -> None:
    """Run the migration once, ignoring corrupt historical state best-effort."""
    try:
        run_historical_auto_name_migration()
    except Exception:
        # Startup and launch should not be bricked by one malformed historical
        # artifact. Registry rebuild still has its own stale-index recovery.
        return


def _migration_marker_path() -> Path:
    return Path.home() / ".sase" / MIGRATION_MARKER_FILENAME


def _marker_is_complete(path: Path) -> bool:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(data, dict)
        and data.get("schema_version") == MIGRATION_SCHEMA_VERSION
        and data.get("completed") is True
    )


def _write_marker(path: Path, mapping: dict[str, str]) -> None:
    payload = {
        "schema_version": MIGRATION_SCHEMA_VERSION,
        "completed": True,
        "migrated_count": len(mapping),
    }
    _write_json_file(path, payload)


def _collect_legacy_auto_name_mapping() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for artifact_dir in _artifact_dirs():
        prefix = _date_prefix_for_artifact(artifact_dir)
        for json_name in ("agent_meta.json", "done.json"):
            data = _read_json_object(artifact_dir / json_name)
            if data is None:
                continue
            for key in _JSON_NAME_KEYS:
                _add_name_mapping(mapping, data.get(key), prefix)

    for bundle_path in _dismissed_bundle_paths():
        data = _read_json_object(bundle_path)
        if data is None:
            continue
        prefix = _date_prefix_for_bundle(bundle_path, data)
        for key in _JSON_NAME_KEYS:
            _add_name_mapping(mapping, data.get(key), prefix)

    env_name = os.environ.get("SASE_AGENT_NAME")
    env_artifacts = os.environ.get("SASE_ARTIFACTS_DIR")
    if env_name and env_artifacts:
        _add_name_mapping(
            mapping,
            env_name,
            _date_prefix_for_artifact(Path(env_artifacts).expanduser()),
        )
    return mapping


def _add_name_mapping(mapping: dict[str, str], value: object, prefix: str) -> None:
    if not isinstance(value, str) or not _is_legacy_auto_name(value):
        return
    mapping.setdefault(value, f"{prefix}.{value}")


def _is_legacy_auto_name(name: str) -> bool:
    return (
        not is_dismissed_prefixed(name)
        and _OLD_AUTO_NAME_RE.fullmatch(name) is not None
    )


def _artifact_dirs() -> list[Path]:
    projects_dir = Path.home() / ".sase" / "projects"
    if not projects_dir.is_dir():
        return []
    dirs: list[Path] = []
    try:
        project_dirs = [p for p in projects_dir.iterdir() if p.is_dir()]
    except OSError:
        return []
    for project_dir in project_dirs:
        artifacts_root = project_dir / "artifacts"
        if not artifacts_root.is_dir():
            continue
        try:
            workflow_dirs = [p for p in artifacts_root.iterdir() if p.is_dir()]
        except OSError:
            continue
        for workflow_dir in workflow_dirs:
            try:
                dirs.extend(p for p in workflow_dir.iterdir() if p.is_dir())
            except OSError:
                continue
    return dirs


def _dismissed_bundle_paths() -> list[Path]:
    bundles_dir = Path.home() / ".sase" / "dismissed_bundles"
    if not bundles_dir.is_dir():
        return []
    try:
        return [path for path in bundles_dir.rglob("*.json") if path.is_file()]
    except OSError:
        return []


def _date_prefix_for_artifact(artifact_dir: Path) -> str:
    for json_name in ("done.json", "agent_meta.json"):
        data = _read_json_object(artifact_dir / json_name)
        if data is None:
            continue
        prefix = _date_prefix_from_payload(data)
        if prefix:
            return prefix
    return _date_prefix_from_raw_suffix(artifact_dir.name)


def _date_prefix_for_bundle(path: Path, data: dict[str, Any]) -> str:
    prefix = _date_prefix_from_payload(data)
    if prefix:
        return prefix
    raw_suffix = data.get("raw_suffix")
    if isinstance(raw_suffix, str):
        return _date_prefix_from_raw_suffix(raw_suffix)
    artifacts_dir = data.get("artifacts_dir")
    if isinstance(artifacts_dir, str) and artifacts_dir:
        return _date_prefix_from_raw_suffix(Path(artifacts_dir).name)
    return _date_prefix_from_raw_suffix(path.stem)


def _date_prefix_from_payload(data: dict[str, Any]) -> str | None:
    for key in ("artifacts_timestamp", "raw_suffix"):
        value = data.get(key)
        if isinstance(value, str):
            prefix = _date_prefix_from_raw_suffix(value)
            if prefix:
                return prefix
    timestamp = data.get("timestamp")
    if isinstance(timestamp, str):
        match = _RUNNER_TIMESTAMP_RE.match(timestamp)
        if match:
            return match.group(1)
        prefix = _date_prefix_from_raw_suffix(timestamp)
        if prefix:
            return prefix
    return None


def _date_prefix_from_raw_suffix(raw_suffix: str) -> str:
    match = _ARTIFACT_SUFFIX_RE.match(raw_suffix)
    if match:
        yyyymmdd = match.group(1)
        return yyyymmdd[2:]
    match = _RUNNER_TIMESTAMP_RE.match(raw_suffix)
    if match:
        return match.group(1)
    return "000000"


def _rewrite_artifact_json_files(mapping: dict[str, str]) -> set[Path]:
    changed: set[Path] = set()
    for artifact_dir in _artifact_dirs():
        for name in ("agent_meta.json", "done.json", "waiting.json", "ready.json"):
            path = artifact_dir / name
            data = _read_json_object(path)
            if data is None:
                continue
            updated = _rewrite_agent_json_payload(data, mapping)
            if updated != data:
                _write_json_file(path, updated)
                changed.add(path)
    env_artifacts = os.environ.get("SASE_ARTIFACTS_DIR")
    if env_artifacts:
        path = Path(env_artifacts).expanduser() / "agent_meta.json"
        data = _read_json_object(path)
        if data is not None:
            updated = _rewrite_agent_json_payload(data, mapping)
            if updated != data:
                _write_json_file(path, updated)
                changed.add(path)
    return changed


def _indexed_artifact_dirs_for_changed_files(paths: Iterable[Path]) -> set[Path]:
    return {
        path.parent for path in paths if path.name in _INDEXED_ARTIFACT_MARKER_NAMES
    }


def _rewrite_agent_json_payload(
    data: dict[str, Any], mapping: dict[str, str]
) -> dict[str, Any]:
    updated = dict(data)
    for key in _JSON_NAME_KEYS:
        if key in updated:
            updated[key] = _rewrite_name_value(updated[key], mapping)
    for key in _JSON_REF_KEYS:
        if key in updated:
            updated[key] = _rewrite_name_value(updated[key], mapping)
    return updated


def _rewrite_dismissed_bundle_files(mapping: dict[str, str]) -> set[Path]:
    changed: set[Path] = set()
    for path in _dismissed_bundle_paths():
        data = _read_json_object(path)
        if data is None:
            continue
        updated = _rewrite_agent_json_payload(data, mapping)
        if updated != data:
            _write_json_file(path, updated)
            changed.add(path)
    return changed


def _rewrite_prompt_artifact_files(mapping: dict[str, str]) -> set[Path]:
    changed: set[Path] = set()
    for artifact_dir in _artifact_dirs():
        path = artifact_dir / "raw_xprompt.md"
        if not path.is_file():
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except OSError:
            continue
        updated = _rewrite_prompt_references(original, mapping)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed.add(path)
    return changed


def _rewrite_prompt_history(mapping: dict[str, str]) -> set[Path]:
    path = Path.home() / ".sase" / "prompt_history.json"
    data = _read_json_object(path)
    if data is None:
        return set()
    prompts = data.get("prompts")
    if not isinstance(prompts, list):
        return set()
    changed = False
    for entry in prompts:
        if not isinstance(entry, dict):
            continue
        text = entry.get("text")
        if not isinstance(text, str):
            continue
        updated = _rewrite_prompt_references(text, mapping)
        if updated != text:
            entry["text"] = updated
            changed = True
    if not changed:
        return set()
    _write_json_file(path, data)
    return {path}


def _rewrite_notifications(mapping: dict[str, str]) -> set[Path]:
    path = Path.home() / ".sase" / "notifications" / "notifications.jsonl"
    if not path.is_file():
        return set()
    lines: list[str] = []
    changed = False
    try:
        original_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    for line in original_lines:
        if not line.strip():
            lines.append(line)
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            lines.append(line)
            continue
        if not isinstance(data, dict):
            lines.append(line)
            continue
        updated = _rewrite_notification_payload(data, mapping)
        if updated != data:
            changed = True
            lines.append(json.dumps(updated, sort_keys=True))
        else:
            lines.append(line)
    if not changed:
        return set()
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {path}


def _rewrite_notification_payload(
    data: dict[str, Any], mapping: dict[str, str]
) -> dict[str, Any]:
    updated = dict(data)
    action_data = updated.get("action_data")
    if isinstance(action_data, dict):
        new_action_data = dict(action_data)
        for key in _NOTIFICATION_ACTION_NAME_KEYS:
            if key in new_action_data:
                new_action_data[key] = _rewrite_name_value(
                    new_action_data[key], mapping
                )
        updated["action_data"] = new_action_data
    return updated


def _rewrite_name_value(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        return [_rewrite_name_value(item, mapping) for item in value]
    if isinstance(value, tuple):
        return tuple(_rewrite_name_value(item, mapping) for item in value)
    return value


def _rewrite_prompt_references(text: str, mapping: dict[str, str]) -> str:
    if not mapping or (
        "%w" not in text
        and "%wait" not in text
        and "#fork" not in text
        and "#resume" not in text
    ):
        return text

    directive = r"(?:%w|%wait|#fork|#resume)"

    def replace_colon(match: re.Match[str]) -> str:
        prefix = match.group("prefix")
        arg = match.group("arg")
        return f"{prefix}{_rewrite_ref_arg(arg, mapping)}"

    def replace_quoted_colon(match: re.Match[str]) -> str:
        prefix = match.group("prefix")
        arg = match.group("arg")
        return f"{prefix}`{_rewrite_ref_arg(arg, mapping)}`"

    text = re.sub(
        rf"(?P<prefix>{directive}:)`(?P<arg>[^`]+)`",
        replace_quoted_colon,
        text,
    )

    text = re.sub(
        rf"(?P<prefix>{directive}:)(?P<arg>[^`\s)]+)",
        replace_colon,
        text,
    )

    def replace_paren(match: re.Match[str]) -> str:
        return (
            f"{match.group('prefix')}{_rewrite_ref_arg(match.group('arg'), mapping)})"
        )

    return re.sub(
        rf"(?P<prefix>{directive}\()(?P<arg>[^)]*)\)",
        replace_paren,
        text,
    )


def _rewrite_ref_arg(arg: str, mapping: dict[str, str]) -> str:
    parts = arg.split(",")
    out: list[str] = []
    for part in parts:
        leading_len = len(part) - len(part.lstrip())
        trailing_len = len(part) - len(part.rstrip())
        leading = part[:leading_len]
        trailing = part[len(part) - trailing_len :] if trailing_len else ""
        core = part.strip()
        out.append(f"{leading}{mapping.get(core, core)}{trailing}")
    return ",".join(out)


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_json_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=f".{os.getpid()}.tmp",
        dir=path.parent,
        text=True,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)
    except OSError:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise
