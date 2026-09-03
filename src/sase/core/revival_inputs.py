"""Launch-time archive of revival inputs that outlives live artifacts.

Publication reads ``raw_xprompt.md`` from the live artifact directory. Cleanup
or chop can delete that directory before the next sidecar sync, which is why
about a third of published v2 run pages have no ``prompt.md``. This store
copies the launch-boundary prompt files into a durable per-run directory under
``~/.sase/revival_inputs/`` as soon as the run starts.

Lookup prefers a parsed ``(project, workflow, timestamp)`` identity so legacy
and day-sharded artifact paths resolve to the same archive. Paths that are not
under the projects root fall back to a digest of the artifacts directory.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import os
from pathlib import Path
import re
import shutil
from typing import Any

from sase.core.agent_artifact_paths import parse_agent_artifact_path
from sase.core.paths import is_valid_sase_project_name, sase_home

_REVIVAL_INPUT_FILENAMES: tuple[str, ...] = (
    "raw_xprompt.md",
    "submitted_xprompt.md",
    "xprompts.json",
)
_REVIVAL_INPUTS_ROOT_NAME = "revival_inputs"
_UNPARSED_ROOT = ".unparsed"
_TIMESTAMP_RE = re.compile(r"^\d{14}$")
_REVIVAL_INPUT_FILENAME_SET = frozenset(_REVIVAL_INPUT_FILENAMES)


def _revival_inputs_dir(
    project_name: str,
    workflow_dir_name: str,
    timestamp: str,
) -> Path:
    """Return the durable archive directory for one parsed run identity."""

    _require_project_name(project_name)
    _require_component(workflow_dir_name, kind="workflow")
    if not _TIMESTAMP_RE.fullmatch(timestamp):
        raise ValueError(f"invalid revival-input timestamp: {timestamp!r}")
    return (
        sase_home()
        / _REVIVAL_INPUTS_ROOT_NAME
        / project_name
        / workflow_dir_name
        / timestamp[:6]
        / timestamp[6:8]
        / timestamp
    )


def _revival_inputs_dir_for_artifacts(artifacts_dir: str | os.PathLike[str]) -> Path:
    """Return the archive directory derived from a live artifacts path."""

    parsed = _parsed_identity(Path(artifacts_dir))
    if parsed is not None:
        return _revival_inputs_dir(*parsed)
    return _unparsed_dir(Path(artifacts_dir))


def capture_revival_inputs(artifacts_dir: str | os.PathLike[str]) -> Path | None:
    """Copy launch-boundary prompt files into the durable per-run archive.

    Copies ``raw_xprompt.md`` and, when present, ``submitted_xprompt.md`` and
    ``xprompts.json``. Returns the archive directory when at least one file was
    copied, otherwise ``None``. Missing sources are skipped; the caller should
    treat failures as best-effort.
    """

    source_root = Path(artifacts_dir)
    if not source_root.is_dir():
        return None
    dest_root = _revival_inputs_dir_for_artifacts(source_root)
    copied = False
    for name in _REVIVAL_INPUT_FILENAMES:
        source = source_root / name
        if not source.is_file():
            continue
        _copy_file_atomic(source, dest_root / name)
        copied = True
    return dest_root if copied else None


def revival_input_file(
    artifacts_dir: str | os.PathLike[str],
    filename: str,
    *,
    project_name: str | None = None,
    workflow_dir_name: str | None = None,
    timestamp: str | None = None,
) -> Path | None:
    """Return an archived revival-input file, or ``None`` when absent."""

    _require_filename(filename)
    by_artifacts = _revival_inputs_dir_for_artifacts(artifacts_dir) / filename
    if by_artifacts.is_file():
        return by_artifacts
    if (
        project_name
        and workflow_dir_name
        and timestamp
        and _TIMESTAMP_RE.fullmatch(timestamp)
        and is_valid_sase_project_name(project_name)
    ):
        try:
            structured = _revival_inputs_dir(project_name, workflow_dir_name, timestamp)
        except ValueError:
            return None
        candidate = structured / filename
        if candidate.is_file():
            return candidate
    return None


def revival_input_file_for_dismissed(
    raw: Mapping[str, Any],
    project_key: str,
    filename: str,
) -> Path | None:
    """Return an archived revival-input file for a dismissed-run bundle."""

    _require_filename(filename)
    artifacts_dir = raw.get("artifacts_dir")
    if isinstance(artifacts_dir, str) and artifacts_dir.strip():
        found = revival_input_file(artifacts_dir, filename)
        if found is not None:
            return found
    timestamp = _dismissed_timestamp(raw)
    if timestamp is None:
        return None
    project_name = _dismissed_project(raw, project_key)
    try:
        candidate = _revival_inputs_dir(project_name, "ace-run", timestamp) / filename
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _parsed_identity(
    artifacts_dir: Path,
) -> tuple[str, str, str] | None:
    try:
        info = parse_agent_artifact_path(artifacts_dir)
    except (ImportError, AttributeError, OSError, TypeError, ValueError):
        return None
    if info is None:
        return None
    if not is_valid_sase_project_name(info.project_name):
        return None
    if not _TIMESTAMP_RE.fullmatch(info.timestamp):
        return None
    try:
        _require_component(info.workflow_dir_name, kind="workflow")
    except ValueError:
        return None
    return info.project_name, info.workflow_dir_name, info.timestamp


def _unparsed_dir(artifacts_dir: Path) -> Path:
    digest = hashlib.sha256(_artifacts_key(artifacts_dir).encode("utf-8")).hexdigest()
    return sase_home() / _REVIVAL_INPUTS_ROOT_NAME / _UNPARSED_ROOT / digest[:32]


def _artifacts_key(artifacts_dir: Path) -> str:
    path = artifacts_dir.expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return os.path.normpath(str(path))


def _copy_file_atomic(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}.tmp")
    try:
        shutil.copyfile(source, tmp)
        os.replace(tmp, dest)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _dismissed_timestamp(raw: Mapping[str, Any]) -> str | None:
    for key in ("raw_suffix", "start_time"):
        value = raw.get(key)
        if isinstance(value, str) and _TIMESTAMP_RE.fullmatch(value):
            return value
    return None


def _dismissed_project(raw: Mapping[str, Any], project_key: str) -> str:
    project_file = raw.get("project_file")
    if isinstance(project_file, str) and project_file:
        name = Path(project_file).expanduser().parent.name
        if is_valid_sase_project_name(name):
            return name
    return project_key


def _require_filename(filename: str) -> None:
    if filename not in _REVIVAL_INPUT_FILENAME_SET:
        raise ValueError(f"unsupported revival-input file: {filename!r}")


def _require_project_name(project_name: str) -> None:
    if not is_valid_sase_project_name(project_name):
        raise ValueError(f"invalid revival-input project: {project_name!r}")


def _require_component(value: str, *, kind: str) -> None:
    if (
        not value
        or value in {".", ".."}
        or value.startswith(".")
        or "/" in value
        or "\\" in value
        or "\x00" in value
    ):
        raise ValueError(f"invalid revival-input {kind}: {value!r}")


__all__ = [
    "capture_revival_inputs",
    "revival_input_file",
    "revival_input_file_for_dismissed",
]
