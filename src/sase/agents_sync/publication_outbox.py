"""Durable typed queue for asynchronous sidecar publication."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import time
from typing import Literal

from sase.agents_sync.io import atomic_write_json
from sase.core.paths import sase_projects_dir, validate_sase_project_name

PUBLICATION_OUTBOX_SCHEMA_VERSION = 4
DEFAULT_PUBLICATION_MAX_ATTEMPTS = 3
_PUBLICATION_MAX_ATTEMPTS_ENV = "SASE_AGENTS_PUBLICATION_MAX_ATTEMPTS"
AGENT_PUBLICATION_OUTBOX_FILENAME = "agents-publication-outbox.json"
PUBLICATION_RETRY_COMMAND = "sase agent sync --retry-quarantined"
PUBLICATION_DROP_COMMAND = "sase agent sync --drop-retired"

PublicationKind = Literal[
    "agent_hood",
    "bead_pages",
    "plan_header",
    "sidecar_push",
]
PublicationLogicalKey = tuple[str, str]
_PUBLICATION_KIND_RANK: dict[PublicationKind, int] = {
    "agent_hood": 0,
    "bead_pages": 1,
    "plan_header": 2,
    "sidecar_push": 3,
}


@dataclass(frozen=True, slots=True)
class AgentPublicationOutboxItem:
    """One idempotent sidecar publication request.

    The historical class name remains part of the public API.  Schema v4 makes
    the record typed while preserving the v1-v3 agent-hood fields and logical
    key exactly.  Non-agent request constructors below keep their irrelevant
    legacy fields empty.
    """

    project_key: str
    project: str
    local_agent: str = ""
    global_agent: str = ""
    primary_revision: str = ""
    local_hood: str = ""
    hood_digest: str = "pending"
    attempts: int = 0
    last_error: str | None = None
    quarantined: bool = False
    quarantined_at: float | None = None
    terminal: bool = False
    terminal_reason: str | None = None
    created_at: float = 0.0
    updated_at: float = 0.0
    kind: PublicationKind = "agent_hood"
    bead_id: str = ""
    lineage_root: str = ""
    plan_ref: str = ""
    commit_message: str = ""
    sidecar_kind: str = ""

    @property
    def logical_key(self) -> PublicationLogicalKey:
        if self.kind == "agent_hood":
            return self.global_agent, self.primary_revision
        if self.kind == "bead_pages":
            return self.lineage_root, self.primary_revision
        if self.kind == "plan_header":
            return self.plan_ref, self.primary_revision
        return self.sidecar_kind, self.project_key

    @property
    def ordering_rank(self) -> int:
        """Stable dependency order used by every queue drainer."""

        return _PUBLICATION_KIND_RANK[self.kind]

    @property
    def id(self) -> str:
        payload = "\0".join(
            (
                self.project_key,
                self.kind,
                *self.logical_key,
                self.hood_digest if self.kind == "agent_hood" else "",
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_json_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "id": self.id,
            "kind": self.kind,
            "rank": self.ordering_rank,
            "project_key": self.project_key,
            "project": self.project,
            "attempts": self.attempts,
            "last_error": self.last_error,
            "quarantined": self.quarantined,
            "quarantined_at": self.quarantined_at,
            "terminal": self.terminal,
            "terminal_reason": self.terminal_reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.kind == "agent_hood":
            result.update(
                {
                    "local_agent": self.local_agent,
                    "global_agent": self.global_agent,
                    "primary_revision": self.primary_revision,
                    "local_hood": self.local_hood,
                    "hood_digest": self.hood_digest,
                }
            )
        elif self.kind == "bead_pages":
            result.update(
                {
                    "bead_id": self.bead_id,
                    "lineage_root": self.lineage_root,
                    "primary_revision": self.primary_revision,
                }
            )
        elif self.kind == "plan_header":
            result.update(
                {
                    "plan_ref": self.plan_ref,
                    "primary_revision": self.primary_revision,
                    "commit_message": self.commit_message,
                }
            )
        else:
            result["sidecar_kind"] = self.sidecar_kind
        return result


# A clearer schema-v4 name for new callers.  Keep the old name above because
# it is imported by agents sync, doctor, and provenance consumers.
SidecarPublicationRequest = AgentPublicationOutboxItem


def _bead_pages_publication_request(
    *,
    project_key: str,
    project: str,
    bead_id: str,
    lineage_root: str,
    primary_revision: str = "",
) -> SidecarPublicationRequest:
    """Build one workspace-independent bead-lineage publication request."""

    return SidecarPublicationRequest(
        project_key=project_key,
        project=project,
        kind="bead_pages",
        bead_id=bead_id,
        lineage_root=lineage_root,
        primary_revision=primary_revision,
    )


def _plan_header_publication_request(
    *,
    project_key: str,
    project: str,
    plan_ref: str,
    primary_revision: str,
    commit_message: str,
) -> SidecarPublicationRequest:
    """Build one workspace-independent committed-plan refresh request."""

    return SidecarPublicationRequest(
        project_key=project_key,
        project=project,
        kind="plan_header",
        plan_ref=plan_ref,
        primary_revision=primary_revision,
        commit_message=commit_message,
    )


def _sidecar_push_publication_request(
    *,
    project_key: str,
    project: str,
    sidecar_kind: str,
) -> SidecarPublicationRequest:
    """Build one coalescing request to push a project's sidecar repository."""

    return SidecarPublicationRequest(
        project_key=project_key,
        project=project,
        kind="sidecar_push",
        sidecar_kind=sidecar_kind,
    )


def _enqueue_sidecar_publication(
    item: SidecarPublicationRequest,
) -> SidecarPublicationRequest:
    """Insert or refresh *item* without duplicating its logical operation."""

    _validate_item(item, item.project_key)
    now = time.time()

    def update(
        items: tuple[SidecarPublicationRequest, ...],
    ) -> tuple[SidecarPublicationRequest, ...]:
        existing = next(
            (
                candidate
                for candidate in items
                if candidate.logical_key == item.logical_key
            ),
            None,
        )
        queued = replace(
            item,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
            attempts=existing.attempts if existing is not None else item.attempts,
            last_error=existing.last_error if existing is not None else item.last_error,
            quarantined=(
                existing.quarantined if existing is not None else item.quarantined
            ),
            quarantined_at=(
                existing.quarantined_at if existing is not None else item.quarantined_at
            ),
            terminal=existing.terminal if existing is not None else item.terminal,
            terminal_reason=(
                existing.terminal_reason
                if existing is not None
                else item.terminal_reason
            ),
            hood_digest=(
                existing.hood_digest
                if item.kind == "agent_hood"
                and existing is not None
                and item.hood_digest == "pending"
                else item.hood_digest
            ),
        )
        return tuple(
            sorted(
                (
                    *(
                        candidate
                        for candidate in items
                        if candidate.logical_key != item.logical_key
                    ),
                    queued,
                ),
                key=_publication_sort_key,
            )
        )

    return next(
        candidate
        for candidate in _mutate_outbox(item.project_key, update)
        if candidate.logical_key == item.logical_key
    )


def enqueue_agent_publication(
    item: AgentPublicationOutboxItem,
) -> AgentPublicationOutboxItem:
    """Backward-compatible agent-hood enqueue entry point."""

    if item.kind != "agent_hood":
        raise ValueError("enqueue_agent_publication requires an agent_hood request")
    return _enqueue_sidecar_publication(item)


def enqueue_bead_pages_publication(
    *,
    project_key: str,
    project: str,
    bead_id: str,
    lineage_root: str | None = None,
    primary_revision: str = "",
) -> SidecarPublicationRequest:
    """Enqueue or coalesce one bead lineage."""

    from sase.bead_pages.paths import bead_lineage_root

    derived_root = bead_lineage_root(bead_id)
    if lineage_root is not None and lineage_root != derived_root:
        raise ValueError(
            f"bead lineage root {lineage_root!r} does not match {bead_id!r}"
        )

    return _enqueue_sidecar_publication(
        _bead_pages_publication_request(
            project_key=project_key,
            project=project,
            bead_id=bead_id,
            lineage_root=derived_root,
            primary_revision=primary_revision,
        )
    )


def enqueue_plan_header_publication(
    *,
    project_key: str,
    project: str,
    plan_ref: str,
    primary_revision: str,
    commit_message: str,
) -> SidecarPublicationRequest:
    """Enqueue or coalesce one committed-plan header refresh."""

    return _enqueue_sidecar_publication(
        _plan_header_publication_request(
            project_key=project_key,
            project=project,
            plan_ref=plan_ref,
            primary_revision=primary_revision,
            commit_message=commit_message,
        )
    )


def enqueue_sidecar_push_publication(
    *,
    project_key: str,
    project: str,
    sidecar_kind: str,
) -> SidecarPublicationRequest:
    """Enqueue or coalesce one sidecar push."""

    return _enqueue_sidecar_publication(
        _sidecar_push_publication_request(
            project_key=project_key,
            project=project,
            sidecar_kind=sidecar_kind,
        )
    )


def list_agent_publications(
    project_key: str,
    *,
    include_quarantined: bool = True,
) -> tuple[AgentPublicationOutboxItem, ...]:
    """Return the durable requests currently queued for *project_key*."""

    with _outbox_lock(project_key):
        items = _read_outbox(_outbox_path(project_key), project_key)
    if include_quarantined:
        return items
    return tuple(item for item in items if not item.quarantined and not item.terminal)


def snapshot_agent_publications_from_path(
    path: Path | str,
    project_key: str,
) -> tuple[AgentPublicationOutboxItem, ...]:
    """Read one immutable typed outbox snapshot without taking its lock.

    Writers atomically replace the complete JSON document with ``os.replace``,
    so a reader observes either the previous complete document or the next
    complete document. This read-only path neither creates a lock file nor
    writes to the project directory.

    Callers pass *path* explicitly because readers already resolve it while
    scanning the projects root, and because ``sase doctor`` reads a projects
    root it was handed rather than the ambient one.
    """

    validate_sase_project_name(project_key)
    return _read_outbox(Path(path), project_key)


def update_agent_publications(
    project_key: str,
    logical_keys: Iterable[tuple[str, str]],
    *,
    hood_digest: str | None = None,
    error: str | None = None,
    increment_attempts: bool = False,
    quarantine_threshold: int | None = None,
    terminal_reason: str | None = None,
) -> tuple[AgentPublicationOutboxItem, ...]:
    """Update matching requests atomically and return the resulting outbox.

    ``terminal_reason`` nominates a failure that cannot be fixed by retrying.
    The request is retired only when its prior recorded error is the same, so
    an indexing race still receives one retry before becoming terminal.
    """

    if quarantine_threshold is not None and quarantine_threshold < 1:
        raise ValueError("publication quarantine threshold must be positive")
    if terminal_reason is not None and error != terminal_reason:
        raise ValueError("terminal publication reason must match the recorded error")
    selected = frozenset(logical_keys)
    now = time.time()

    def update(
        items: tuple[AgentPublicationOutboxItem, ...],
    ) -> tuple[AgentPublicationOutboxItem, ...]:
        updated: list[AgentPublicationOutboxItem] = []
        for item in items:
            if item.logical_key not in selected:
                updated.append(item)
                continue
            attempts = item.attempts + int(increment_attempts)
            terminal = item.terminal or (
                terminal_reason is not None
                and item.attempts > 0
                and item.last_error == terminal_reason
            )
            quarantine = not terminal and (
                item.quarantined
                or (
                    quarantine_threshold is not None
                    and attempts >= quarantine_threshold
                )
            )
            updated.append(
                replace(
                    item,
                    hood_digest=hood_digest or item.hood_digest,
                    last_error=error,
                    attempts=attempts,
                    quarantined=quarantine,
                    quarantined_at=(
                        item.quarantined_at
                        if quarantine and item.quarantined
                        else now
                        if quarantine
                        else None
                    ),
                    terminal=terminal,
                    terminal_reason=(
                        item.terminal_reason
                        if item.terminal
                        else terminal_reason
                        if terminal
                        else None
                    ),
                    updated_at=now,
                )
            )
        return tuple(updated)

    return _mutate_outbox(project_key, update)


def clear_quarantined_agent_publications(
    project_key: str,
) -> tuple[AgentPublicationOutboxItem, ...]:
    """Return quarantined requests to the active queue with a fresh retry budget."""

    now = time.time()

    def update(
        items: tuple[AgentPublicationOutboxItem, ...],
    ) -> tuple[AgentPublicationOutboxItem, ...]:
        return tuple(
            replace(
                item,
                attempts=0,
                last_error=None,
                quarantined=False,
                quarantined_at=None,
                updated_at=now,
            )
            if item.quarantined and not item.terminal
            else item
            for item in items
        )

    return _mutate_outbox(project_key, update)


def drop_terminal_agent_publications(
    project_key: str,
) -> tuple[AgentPublicationOutboxItem, ...]:
    """Remove retired requests from *project_key* and return the dropped ones."""

    dropped: list[AgentPublicationOutboxItem] = []

    def update(
        items: tuple[AgentPublicationOutboxItem, ...],
    ) -> tuple[AgentPublicationOutboxItem, ...]:
        dropped.extend(item for item in items if item.terminal)
        return tuple(item for item in items if not item.terminal)

    _mutate_outbox(project_key, update)
    return tuple(dropped)


def configured_publication_max_attempts() -> int:
    """Return the bounded per-item preparation retry threshold."""

    raw = os.environ.get(_PUBLICATION_MAX_ATTEMPTS_ENV)
    if raw is None:
        return DEFAULT_PUBLICATION_MAX_ATTEMPTS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_PUBLICATION_MAX_ATTEMPTS
    return value if value > 0 else DEFAULT_PUBLICATION_MAX_ATTEMPTS


def publication_quarantine_diagnostics(project_key: str) -> tuple[str, ...]:
    """Render stable diagnostics for stopped requests in *project_key*.

    A quarantined request is retryable and names the retry command; a retired
    request can never be published and names the drop command instead.
    """

    return tuple(
        _publication_stopped_diagnostic(item)
        for item in list_agent_publications(project_key)
        if item.terminal or item.quarantined
    )


def _publication_stopped_diagnostic(item: AgentPublicationOutboxItem) -> str:
    """Render one quarantined or retired request with accurate remediation."""

    subject = f"publication request {_publication_subject(item)}"
    if item.terminal:
        reason = item.terminal_reason or item.last_error or "unknown reason"
        return (
            f"{subject} retired as unpublishable: {reason}; run "
            f"`{PUBLICATION_DROP_COMMAND}` to drop it"
        )
    return (
        f"{subject} quarantined after {item.attempts} attempts: "
        f"{item.last_error or 'unknown error'}; run "
        f"`{PUBLICATION_RETRY_COMMAND}` to retry"
    )


def _publication_subject(item: SidecarPublicationRequest) -> str:
    if item.kind == "agent_hood":
        return f"{item.global_agent}@{item.primary_revision[:12]}"
    if item.kind == "bead_pages":
        suffix = f"@{item.primary_revision[:12]}" if item.primary_revision else ""
        return f"bead lineage {item.lineage_root}{suffix}"
    if item.kind == "plan_header":
        return f"plan {item.plan_ref}@{item.primary_revision[:12]}"
    return f"{item.sidecar_kind} sidecar for {item.project}"


def acknowledge_agent_publications(
    project_key: str,
    logical_keys: Iterable[tuple[str, str]],
) -> tuple[AgentPublicationOutboxItem, ...]:
    """Remove successfully published requests and return the remaining outbox."""

    selected = frozenset(logical_keys)
    return _mutate_outbox(
        project_key,
        lambda items: tuple(item for item in items if item.logical_key not in selected),
    )


def _mutate_outbox(
    project_key: str,
    update: Callable[
        [tuple[AgentPublicationOutboxItem, ...]],
        tuple[AgentPublicationOutboxItem, ...],
    ],
) -> tuple[AgentPublicationOutboxItem, ...]:
    with _outbox_lock(project_key):
        path = _outbox_path(project_key)
        items = update(_read_outbox(path, project_key))
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            path,
            {
                "schema_version": PUBLICATION_OUTBOX_SCHEMA_VERSION,
                "items": [item.to_json_dict() for item in items],
            },
        )
        return items


def _outbox_path(project_key: str) -> Path:
    validate_sase_project_name(project_key)
    return sase_projects_dir() / project_key / AGENT_PUBLICATION_OUTBOX_FILENAME


@contextmanager
def _outbox_lock(project_key: str) -> Iterator[None]:
    path = _outbox_path(project_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_outbox(
    path: Path,
    project_key: str,
) -> tuple[AgentPublicationOutboxItem, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ()
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not read agents publication outbox: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("agents publication outbox must be a JSON object")
    schema_version = payload.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version not in {1, 2, 3, PUBLICATION_OUTBOX_SCHEMA_VERSION}
    ):
        raise RuntimeError("unsupported agents publication outbox schema")
    rows = payload.get("items")
    if not isinstance(rows, list):
        raise RuntimeError("agents publication outbox items must be a list")
    items = tuple(
        _item_from_json(row, project_key, schema_version=schema_version) for row in rows
    )
    if len({item.logical_key for item in items}) != len(items):
        raise RuntimeError("agents publication outbox contains duplicate requests")
    # Rank is the only cross-kind ordering constraint.  Python's stable sort
    # preserves the durable order within one kind, including legacy files.
    return tuple(sorted(items, key=lambda item: item.ordering_rank))


def _item_from_json(
    value: object,
    project_key: str,
    *,
    schema_version: int,
) -> AgentPublicationOutboxItem:
    if not isinstance(value, dict):
        raise RuntimeError("agents publication outbox item must be an object")
    row = value
    kind = (
        "agent_hood"
        if schema_version < PUBLICATION_OUTBOX_SCHEMA_VERSION
        else _json_publication_kind(row, "kind")
    )
    if schema_version == PUBLICATION_OUTBOX_SCHEMA_VERSION:
        rank = _json_nonnegative_int(row, "rank", default=-1)
        if rank != _PUBLICATION_KIND_RANK[kind]:
            raise RuntimeError("agents publication outbox rank does not match kind")
    item = AgentPublicationOutboxItem(
        project_key=_json_text(row, "project_key"),
        project=_json_text(row, "project"),
        local_agent=_json_text(row, "local_agent", default=""),
        global_agent=_json_text(row, "global_agent", default=""),
        primary_revision=_json_text(row, "primary_revision"),
        local_hood=_json_text(row, "local_hood", default=""),
        hood_digest=_json_text(row, "hood_digest", default="pending"),
        kind=kind,
        bead_id=_json_text(row, "bead_id", default=""),
        lineage_root=_json_text(row, "lineage_root", default=""),
        plan_ref=_json_text(row, "plan_ref", default=""),
        commit_message=_json_text(row, "commit_message", default=""),
        sidecar_kind=_json_text(row, "sidecar_kind", default=""),
        attempts=_json_nonnegative_int(row, "attempts", default=0),
        last_error=_json_optional_text(row, "last_error"),
        quarantined=_json_boolean(
            row,
            "quarantined",
            default=False if schema_version == 1 else None,
        ),
        quarantined_at=_json_optional_number(row, "quarantined_at"),
        terminal=_json_boolean(
            row,
            "terminal",
            default=False if schema_version < 3 else None,
        ),
        terminal_reason=_json_optional_text(row, "terminal_reason"),
        created_at=_json_number(row, "created_at", default=0.0),
        updated_at=_json_number(row, "updated_at", default=0.0),
    )
    _validate_item(item, project_key)
    return item


def _validate_item(item: SidecarPublicationRequest, project_key: str) -> None:
    if item.project_key != project_key:
        raise RuntimeError("agents publication outbox project identity mismatch")
    if not item.project_key or not item.project:
        raise RuntimeError("agents publication outbox item is incomplete")
    required: tuple[str, ...]
    if item.kind == "agent_hood":
        required = (
            item.local_agent,
            item.global_agent,
            item.primary_revision,
            item.local_hood,
        )
    elif item.kind == "bead_pages":
        required = (item.bead_id, item.lineage_root)
    elif item.kind == "plan_header":
        required = (item.plan_ref, item.primary_revision, item.commit_message)
    else:
        required = (item.sidecar_kind,)
    if not all(required):
        raise RuntimeError("agents publication outbox item is incomplete")


def _publication_sort_key(
    item: SidecarPublicationRequest,
) -> tuple[int, float, str]:
    return item.ordering_rank, item.created_at, item.id


def _json_text(
    row: dict[object, object],
    field: str,
    *,
    default: str = "",
) -> str:
    value = row.get(field, default)
    if not isinstance(value, str):
        raise RuntimeError(f"agents publication outbox {field} must be a string")
    return value


def _json_publication_kind(
    row: dict[object, object],
    field: str,
) -> PublicationKind:
    value = row.get(field)
    if value not in _PUBLICATION_KIND_RANK:
        raise RuntimeError(
            "agents publication outbox kind must be one of: "
            + ", ".join(_PUBLICATION_KIND_RANK)
        )
    return value  # type: ignore[return-value]


def _json_optional_text(
    row: dict[object, object],
    field: str,
) -> str | None:
    value = row.get(field)
    if value is not None and not isinstance(value, str):
        raise RuntimeError(
            f"agents publication outbox {field} must be a string or null"
        )
    return value


def _json_boolean(
    row: dict[object, object],
    field: str,
    *,
    default: bool | None,
) -> bool:
    value = row.get(field, default)
    if not isinstance(value, bool):
        raise RuntimeError(f"agents publication outbox {field} must be a boolean")
    return value


def _json_nonnegative_int(
    row: dict[object, object],
    field: str,
    *,
    default: int,
) -> int:
    value = row.get(field, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeError(
            f"agents publication outbox {field} must be a non-negative integer"
        )
    return value


def _json_number(
    row: dict[object, object],
    field: str,
    *,
    default: float,
) -> float:
    value = row.get(field, default)
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise RuntimeError(f"agents publication outbox {field} must be a number")
    return float(value)


def _json_optional_number(
    row: dict[object, object],
    field: str,
) -> float | None:
    value = row.get(field)
    if value is None:
        return None
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise RuntimeError(
            f"agents publication outbox {field} must be a number or null"
        )
    return float(value)


__all__ = [
    "AGENT_PUBLICATION_OUTBOX_FILENAME",
    "DEFAULT_PUBLICATION_MAX_ATTEMPTS",
    "PUBLICATION_DROP_COMMAND",
    "PUBLICATION_OUTBOX_SCHEMA_VERSION",
    "PUBLICATION_RETRY_COMMAND",
    "AgentPublicationOutboxItem",
    "PublicationKind",
    "PublicationLogicalKey",
    "SidecarPublicationRequest",
    "acknowledge_agent_publications",
    "clear_quarantined_agent_publications",
    "configured_publication_max_attempts",
    "drop_terminal_agent_publications",
    "enqueue_agent_publication",
    "enqueue_bead_pages_publication",
    "enqueue_plan_header_publication",
    "enqueue_sidecar_push_publication",
    "list_agent_publications",
    "publication_quarantine_diagnostics",
    "snapshot_agent_publications_from_path",
    "update_agent_publications",
]
