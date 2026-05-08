"""Reusable agent artifact domain and explicit-artifact index.

This module is intentionally independent of the Agents-tab TUI. It owns the
small artifact model, durable explicit-artifact storage under
``~/.sase/artifacts/``, and default artifact synthesis from existing per-run
metadata.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from collections.abc import Iterator

AgentArtifactKind = Literal["chat", "plan", "image", "markdown", "pdf", "file"]

AGENT_ARTIFACT_INDEX_SCHEMA_VERSION = 1
AGENT_ARTIFACT_KINDS: tuple[AgentArtifactKind, ...] = (
    "chat",
    "plan",
    "image",
    "markdown",
    "pdf",
    "file",
)

_IMAGE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
}
_MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdown", ".mkd"}
_JSONL_INDEX_NAME = "index.jsonl"
_LOCK_NAME = "index.lock"


# pyvision: public_api_methods.txt
@dataclass(frozen=True)
class AgentArtifactAssociation:
    """Stable identity for artifacts associated with one agent run."""

    agent_artifacts_dir: str
    project: str | None = None
    workflow: str | None = None
    raw_timestamp: str | None = None
    agent_name: str | None = None


# pyvision: public_api_methods.txt
@dataclass(frozen=True)
class AgentArtifact:
    """One artifact available for a SASE agent."""

    id: str
    label: str
    kind: AgentArtifactKind
    path: str
    source_path: str | None = None
    created_at: str | None = None
    agent_artifacts_dir: str | None = None
    project: str | None = None
    workflow: str | None = None
    raw_timestamp: str | None = None
    agent_name: str | None = None
    explicit: bool = False


# pyvision: public_api_methods.txt
def default_artifacts_root(sase_home: Path | str | None = None) -> Path:
    """Return the directory used for explicit user/agent artifacts."""

    root = (
        Path(sase_home).expanduser() if sase_home is not None else Path.home() / ".sase"
    )
    return root / "artifacts"


# pyvision: public_api_methods.txt
def default_agent_artifacts_index_path(sase_home: Path | str | None = None) -> Path:
    """Return the JSONL index path for explicit agent artifacts."""

    return default_artifacts_root(sase_home) / _JSONL_INDEX_NAME


# pyvision: public_api_methods.txt
def agent_artifact_to_dict(artifact: AgentArtifact) -> dict[str, Any]:
    """Project an artifact model to a JSON-safe dict."""

    return asdict(artifact)


# pyvision: public_api_methods.txt
def agent_artifact_from_dict(data: dict[str, Any]) -> AgentArtifact:
    """Rehydrate an artifact model from a JSON-safe dict."""

    kind = _coerce_kind(data.get("kind"))
    return AgentArtifact(
        id=str(data["id"]),
        label=str(data["label"]),
        kind=kind,
        path=str(data["path"]),
        source_path=_optional_str(data.get("source_path")),
        created_at=_optional_str(data.get("created_at")),
        agent_artifacts_dir=_optional_str(data.get("agent_artifacts_dir")),
        project=_optional_str(data.get("project")),
        workflow=_optional_str(data.get("workflow")),
        raw_timestamp=_optional_str(data.get("raw_timestamp")),
        agent_name=_optional_str(data.get("agent_name")),
        explicit=bool(data.get("explicit", False)),
    )


# pyvision: public_api_methods.txt
def artifact_association_from_dir(
    agent_artifacts_dir: Path | str,
    *,
    agent_name: str | None = None,
) -> AgentArtifactAssociation:
    """Derive stable agent association fields from an artifact directory path."""

    artifacts_dir = Path(agent_artifacts_dir).expanduser()
    project: str | None = None
    workflow: str | None = None
    raw_timestamp: str | None = artifacts_dir.name or None
    parts = artifacts_dir.parts
    for index, part in enumerate(parts):
        if part == "projects" and len(parts) > index + 4:
            project = parts[index + 1]
            if parts[index + 2] == "artifacts":
                workflow = parts[index + 3]
                raw_timestamp = parts[index + 4]
            break
    return AgentArtifactAssociation(
        agent_artifacts_dir=str(artifacts_dir),
        project=project,
        workflow=workflow,
        raw_timestamp=raw_timestamp,
        agent_name=agent_name,
    )


def store_explicit_agent_artifact(
    source_path: Path | str,
    agent_artifacts_dir: Path | str,
    *,
    label: str | None = None,
    kind: AgentArtifactKind | str | None = None,
    artifacts_root: Path | str | None = None,
    index_path: Path | str | None = None,
    move: bool = False,
    created_at: str | None = None,
) -> AgentArtifact:
    """Store an explicit artifact and upsert its persistent association.

    By default the source file is copied. Pass ``move=True`` when called from a
    command that should relocate the file into ``~/.sase/artifacts/``.
    """

    source = Path(source_path).expanduser()
    if not source.is_file():
        raise FileNotFoundError(str(source))

    root = (
        Path(artifacts_root).expanduser()
        if artifacts_root
        else default_artifacts_root()
    )
    idx = Path(index_path).expanduser() if index_path else root / _JSONL_INDEX_NAME
    association = _association_from_metadata(agent_artifacts_dir)
    artifact_kind = (
        _coerce_kind(kind) if kind is not None else infer_artifact_kind(source)
    )
    stored_path = _store_file(source, root, association, move=move)
    artifact = AgentArtifact(
        id=_artifact_id("explicit", association, stored_path, label or source.name),
        label=label or source.name,
        kind=artifact_kind,
        path=str(stored_path),
        source_path=str(source),
        created_at=created_at or _now_iso(),
        agent_artifacts_dir=association.agent_artifacts_dir,
        project=association.project,
        workflow=association.workflow,
        raw_timestamp=association.raw_timestamp,
        agent_name=association.agent_name,
        explicit=True,
    )
    _upsert_index_row(idx, artifact)
    return artifact


def read_explicit_agent_artifact_index(
    index_path: Path | str | None = None,
) -> list[AgentArtifact]:
    """Read all explicit artifact rows from the persistent index."""

    idx = (
        Path(index_path).expanduser()
        if index_path
        else default_agent_artifacts_index_path()
    )
    if not idx.exists():
        return []
    with _index_lock(idx, exclusive=False):
        return _read_index_unlocked(idx)


def list_explicit_agent_artifacts(
    agent_artifacts_dir: Path | str,
    *,
    index_path: Path | str | None = None,
) -> list[AgentArtifact]:
    """Return explicit artifacts associated with one agent run."""

    association = artifact_association_from_dir(agent_artifacts_dir)
    rows = read_explicit_agent_artifact_index(index_path)
    return [row for row in rows if _matches_association(row, association)]


def synthesize_default_agent_artifacts(
    agent_artifacts_dir: Path | str,
) -> list[AgentArtifact]:
    """Synthesize chat/plan/image artifacts from existing run metadata."""

    artifacts_dir = Path(agent_artifacts_dir).expanduser()
    done = _read_json_object(artifacts_dir / "done.json")
    agent_meta = _read_json_object(artifacts_dir / "agent_meta.json")
    plan_marker = _read_json_object(artifacts_dir / "plan_path.json")
    association = _association_from_metadata(
        artifacts_dir, done=done, agent_meta=agent_meta
    )

    artifacts: list[AgentArtifact] = []

    chat_path = _first_str(done.get("response_path"), agent_meta.get("chat_path"))
    if chat_path:
        artifacts.append(
            _default_artifact(
                association,
                label="Chat transcript",
                kind="chat",
                path=chat_path,
                ordinal="chat",
            )
        )

    for index, plan_path in enumerate(
        _unique_values(
            done.get("plan_path"),
            agent_meta.get("plan_path"),
            agent_meta.get("sdd_plan_path"),
            plan_marker.get("plan_path"),
        )
    ):
        artifacts.append(
            _default_artifact(
                association,
                label=_label_for_path(plan_path, fallback="Plan"),
                kind="plan",
                path=plan_path,
                ordinal=f"plan-{index}",
            )
        )

    for index, image_path in enumerate(_coerce_str_list(done.get("image_paths"))):
        artifacts.append(
            _default_artifact(
                association,
                label=_label_for_path(image_path, fallback="Image"),
                kind="image",
                path=image_path,
                ordinal=f"image-{index}",
            )
        )

    for index, pdf_path in enumerate(_coerce_str_list(done.get("markdown_pdf_paths"))):
        artifacts.append(
            _default_artifact(
                association,
                label=_label_for_path(pdf_path, fallback="PDF"),
                kind="pdf",
                path=pdf_path,
                ordinal=f"pdf-{index}",
            )
        )

    return _dedupe_artifacts(artifacts)


def list_agent_artifacts(
    agent_artifacts_dir: Path | str,
    *,
    index_path: Path | str | None = None,
) -> list[AgentArtifact]:
    """Return default plus explicit artifacts for one agent in display order."""

    defaults = synthesize_default_agent_artifacts(agent_artifacts_dir)
    explicit = list_explicit_agent_artifacts(
        agent_artifacts_dir,
        index_path=index_path,
    )
    images_and_generated = [
        artifact for artifact in defaults if artifact.kind not in {"chat", "plan"}
    ]
    chat_and_plans = [
        artifact for artifact in defaults if artifact.kind in {"chat", "plan"}
    ]
    return _dedupe_artifacts([*chat_and_plans, *explicit, *images_and_generated])


# pyvision: public_api_methods.txt
def infer_artifact_kind(path: Path | str) -> AgentArtifactKind:
    """Infer an artifact kind from a path suffix."""

    suffix = Path(path).suffix.lower()
    if suffix in _IMAGE_SUFFIXES:
        return "image"
    if suffix in _MARKDOWN_SUFFIXES:
        return "markdown"
    if suffix == ".pdf":
        return "pdf"
    return "file"


def _association_from_metadata(
    agent_artifacts_dir: Path | str,
    *,
    done: dict[str, Any] | None = None,
    agent_meta: dict[str, Any] | None = None,
) -> AgentArtifactAssociation:
    artifacts_dir = Path(agent_artifacts_dir).expanduser()
    done_data = (
        done if done is not None else _read_json_object(artifacts_dir / "done.json")
    )
    meta_data = (
        agent_meta
        if agent_meta is not None
        else _read_json_object(artifacts_dir / "agent_meta.json")
    )
    agent_name = _first_str(done_data.get("name"), meta_data.get("name"))
    return artifact_association_from_dir(artifacts_dir, agent_name=agent_name)


def _store_file(
    source: Path,
    artifacts_root: Path,
    association: AgentArtifactAssociation,
    *,
    move: bool,
) -> Path:
    target_dir = (
        artifacts_root
        / "agents"
        / _safe_segment(association.project or "unknown-project")
        / _safe_segment(
            association.raw_timestamp
            or _hash_text(association.agent_artifacts_dir)[:12]
        )
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix
    stem = _safe_segment(source.stem) or "artifact"
    digest = _hash_file(source)[:12]
    target = target_dir / f"{stem}-{digest}{suffix}"
    if target.exists():
        if move and source.resolve(strict=False) != target.resolve(strict=False):
            source.unlink()
        return target

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target_dir,
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        shutil.copy2(source, tmp_path)
        os.replace(tmp_path, target)
        if move:
            source.unlink()
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return target


def _upsert_index_row(index_path: Path, artifact: AgentArtifact) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with _index_lock(index_path, exclusive=True):
        rows = _read_index_unlocked(index_path)
        rows_by_id = {row.id: row for row in rows}
        rows_by_id[artifact.id] = artifact
        _write_index_unlocked(index_path, list(rows_by_id.values()))


def _read_index_unlocked(index_path: Path) -> list[AgentArtifact]:
    if not index_path.exists():
        return []
    rows: list[AgentArtifact] = []
    with index_path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            data = json.loads(stripped)
            if (
                int(data.get("schema_version", 0))
                != AGENT_ARTIFACT_INDEX_SCHEMA_VERSION
            ):
                continue
            artifact_data = data.get("artifact")
            if isinstance(artifact_data, dict):
                rows.append(agent_artifact_from_dict(artifact_data))
    return rows


def _write_index_unlocked(index_path: Path, rows: list[AgentArtifact]) -> None:
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=f".{index_path.name}.",
        suffix=".tmp",
        dir=index_path.parent,
        text=True,
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(
                    json.dumps(
                        {
                            "schema_version": AGENT_ARTIFACT_INDEX_SCHEMA_VERSION,
                            "artifact": agent_artifact_to_dict(row),
                        },
                        sort_keys=True,
                    )
                )
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, index_path)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


@contextmanager
def _index_lock(index_path: Path, *, exclusive: bool) -> Iterator[None]:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = index_path.parent / _LOCK_NAME
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _default_artifact(
    association: AgentArtifactAssociation,
    *,
    label: str,
    kind: AgentArtifactKind,
    path: str,
    ordinal: str,
) -> AgentArtifact:
    return AgentArtifact(
        id=_artifact_id(f"default-{ordinal}", association, path, label),
        label=label,
        kind=kind,
        path=path,
        source_path=path,
        created_at=_file_created_at(path),
        agent_artifacts_dir=association.agent_artifacts_dir,
        project=association.project,
        workflow=association.workflow,
        raw_timestamp=association.raw_timestamp,
        agent_name=association.agent_name,
        explicit=False,
    )


def _dedupe_artifacts(artifacts: list[AgentArtifact]) -> list[AgentArtifact]:
    seen: set[str] = set()
    deduped: list[AgentArtifact] = []
    for artifact in artifacts:
        key = _path_key(artifact.path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(artifact)
    return deduped


def _matches_association(
    artifact: AgentArtifact,
    association: AgentArtifactAssociation,
) -> bool:
    if artifact.agent_artifacts_dir == association.agent_artifacts_dir:
        return True
    return (
        artifact.project is not None
        and artifact.project == association.project
        and artifact.raw_timestamp is not None
        and artifact.raw_timestamp == association.raw_timestamp
    )


def _artifact_id(
    prefix: str,
    association: AgentArtifactAssociation,
    path: Path | str,
    label: str,
) -> str:
    identity = "|".join(
        [
            association.project or "",
            association.workflow or "",
            association.raw_timestamp or "",
            association.agent_artifacts_dir,
            _path_key(path),
            label,
        ]
    )
    return f"{prefix}:{_hash_text(identity)[:24]}"


def _path_key(path: Path | str) -> str:
    expanded = Path(path).expanduser()
    return str(expanded.resolve(strict=False))


def _hash_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_segment(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    return safe.strip(".-")[:80]


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _coerce_kind(kind: Any) -> AgentArtifactKind:
    if kind in AGENT_ARTIFACT_KINDS:
        return kind
    raise ValueError(f"unsupported artifact kind: {kind!r}")


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _first_str(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def _coerce_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _unique_values(*values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        key = _path_key(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _label_for_path(path: str, *, fallback: str) -> str:
    name = Path(path).name
    return name or fallback


def _file_created_at(path: Path | str) -> str | None:
    try:
        stat = Path(path).expanduser().stat()
    except OSError:
        return None
    return datetime.fromtimestamp(stat.st_mtime, UTC).isoformat()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


__all__ = [
    "AGENT_ARTIFACT_INDEX_SCHEMA_VERSION",
    "AGENT_ARTIFACT_KINDS",
    "AgentArtifact",
    "AgentArtifactAssociation",
    "AgentArtifactKind",
    "agent_artifact_from_dict",
    "agent_artifact_to_dict",
    "artifact_association_from_dir",
    "default_agent_artifacts_index_path",
    "default_artifacts_root",
    "infer_artifact_kind",
    "list_agent_artifacts",
    "list_explicit_agent_artifacts",
    "read_explicit_agent_artifact_index",
    "store_explicit_agent_artifact",
    "synthesize_default_agent_artifacts",
]
