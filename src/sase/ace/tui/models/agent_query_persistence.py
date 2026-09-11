"""Machine-local restart persistence for the live Agents tab query."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, Literal

from sase.ace.query_record import QueryRecord, current_profile_digest
from sase.core.paths import sase_home

log = logging.getLogger(__name__)

type AgentQueryDialect = Literal["agents-live", "agents-legacy"]

SCHEMA_VERSION = 1
FILENAME = "ace_agents_last_query.json"
MAX_FILE_BYTES = 64 * 1024
DIALECT_UNIFIED: AgentQueryDialect = "agents-live"
DIALECT_LEGACY: AgentQueryDialect = "agents-legacy"

_KNOWN_DIALECTS = frozenset({DIALECT_UNIFIED, DIALECT_LEGACY})
_WRITE_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class AgentQuerySnapshot:
    """One committed Agents query plus the dialect that produced it."""

    dialect: AgentQueryDialect
    record: QueryRecord

    @property
    def source(self) -> str:
        return self.record.source

    def to_wire(self) -> dict[str, Any]:
        """Return the deterministic JSON-safe payload."""
        return {
            "schema_version": SCHEMA_VERSION,
            "dialect": self.dialect,
            "record": self.record.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class AgentQueryLoadResult:
    """Result of reading and validating the persisted Agents query."""

    snapshot: AgentQuerySnapshot | None = None
    warning: str | None = None
    missing: bool = False

    @property
    def accepted(self) -> bool:
        return self.snapshot is not None


class AgentQueryPersistenceError(ValueError):
    """Raised internally when a saved Agents query record is unusable."""


def active_agent_query_dialect() -> AgentQueryDialect:
    """Return the active Agents-tab query dialect."""
    from .agent_live_query_engine import agents_unified_query_enabled

    return DIALECT_UNIFIED if agents_unified_query_enabled() else DIALECT_LEGACY


def agent_query_state_path() -> Path:
    """Return the machine-local Agents query resume-state path."""
    return sase_home() / FILENAME


def make_agent_query_snapshot(
    source: str,
    *,
    dialect: AgentQueryDialect | None = None,
) -> AgentQuerySnapshot:
    """Build a validated snapshot for one explicit committed source string."""
    resolved_dialect = dialect or active_agent_query_dialect()
    if resolved_dialect not in _KNOWN_DIALECTS:
        raise AgentQueryPersistenceError("unknown Agents query dialect")
    normalized_source = "" if not source.strip() else source
    canonical = _canonical_for_dialect(normalized_source, resolved_dialect)
    digest = (
        current_profile_digest(DIALECT_UNIFIED)
        if resolved_dialect == DIALECT_UNIFIED and normalized_source
        else None
    )
    return AgentQuerySnapshot(
        dialect=resolved_dialect,
        record=QueryRecord(
            source=normalized_source,
            canonical=canonical,
            profile_digest=digest,
        ),
    )


def load_agent_query_snapshot(
    *,
    active_dialect: AgentQueryDialect | None = None,
    path: Path | None = None,
) -> AgentQueryLoadResult:
    """Load and validate the remembered Agents query for the active dialect."""
    resolved_dialect = active_dialect or active_agent_query_dialect()
    state_path = path or agent_query_state_path()
    try:
        with state_path.open("rb") as stream:
            raw_bytes = stream.read(MAX_FILE_BYTES + 1)
    except FileNotFoundError:
        return AgentQueryLoadResult(missing=True)
    except OSError:
        log.warning("Unable to read Agents query state: %s", state_path, exc_info=True)
        return AgentQueryLoadResult(
            warning="Could not read the saved Agents query; submit a query to replace it."
        )

    if len(raw_bytes) > MAX_FILE_BYTES:
        return AgentQueryLoadResult(
            warning="Saved Agents query is too large; submit a query to replace it."
        )
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except UnicodeDecodeError:
        return AgentQueryLoadResult(
            warning="Saved Agents query is not valid UTF-8; submit a query to replace it."
        )
    except json.JSONDecodeError:
        return AgentQueryLoadResult(
            warning="Saved Agents query is not valid JSON; submit a query to replace it."
        )

    try:
        snapshot = _decode_snapshot(payload)
        compatible = _validate_for_active_dialect(snapshot, resolved_dialect)
    except AgentQueryPersistenceError as exc:
        return AgentQueryLoadResult(warning=str(exc))
    return AgentQueryLoadResult(snapshot=compatible)


def save_agent_query_snapshot(
    snapshot: AgentQuerySnapshot,
    *,
    path: Path | None = None,
) -> None:
    """Atomically persist one complete Agents query snapshot."""
    state_path = path or agent_query_state_path()
    serialized = _serialize_snapshot(snapshot)
    state_path.parent.mkdir(parents=True, exist_ok=True)

    temporary: Path | None = None
    fd: int | None = None
    with _WRITE_LOCK:
        try:
            fd, temporary_name = tempfile.mkstemp(
                prefix=f".{state_path.name}.",
                suffix=".tmp",
                dir=state_path.parent,
            )
            temporary = Path(temporary_name)
            with os.fdopen(fd, "wb") as stream:
                fd = None
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            _replace_state_file(temporary, state_path)
            _fsync_directory(state_path.parent)
        except BaseException:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            raise


def _decode_snapshot(payload: Any) -> AgentQuerySnapshot:
    if not isinstance(payload, dict):
        raise AgentQueryPersistenceError(
            "Saved Agents query has an invalid shape; submit a query to replace it."
        )
    if set(payload) != {"schema_version", "dialect", "record"}:
        raise AgentQueryPersistenceError(
            "Saved Agents query has an invalid shape; submit a query to replace it."
        )
    version = payload.get("schema_version")
    if type(version) is not int or version != SCHEMA_VERSION:
        raise AgentQueryPersistenceError(
            "Saved Agents query uses an unsupported version; submit a query to replace it."
        )
    dialect = payload.get("dialect")
    if dialect not in _KNOWN_DIALECTS:
        raise AgentQueryPersistenceError(
            "Saved Agents query uses an unknown dialect; submit a query to replace it."
        )
    record = _decode_record(payload.get("record"))
    return AgentQuerySnapshot(dialect=dialect, record=record)


def _decode_record(payload: Any) -> QueryRecord:
    if not isinstance(payload, dict):
        raise AgentQueryPersistenceError(
            "Saved Agents query has an invalid record; submit a query to replace it."
        )
    if set(payload) != {"source", "canonical", "profile_digest"}:
        raise AgentQueryPersistenceError(
            "Saved Agents query has an invalid record; submit a query to replace it."
        )
    source = payload.get("source")
    canonical = payload.get("canonical")
    digest = payload.get("profile_digest")
    if not isinstance(source, str) or not isinstance(canonical, str):
        raise AgentQueryPersistenceError(
            "Saved Agents query has an invalid record; submit a query to replace it."
        )
    if digest is not None and not isinstance(digest, str):
        raise AgentQueryPersistenceError(
            "Saved Agents query has an invalid record; submit a query to replace it."
        )
    normalized_source = "" if not source.strip() else source
    normalized_canonical = "" if not canonical.strip() else canonical
    return QueryRecord(
        source=normalized_source,
        canonical=normalized_canonical,
        profile_digest=digest,
    )


def _validate_for_active_dialect(
    snapshot: AgentQuerySnapshot,
    active_dialect: AgentQueryDialect,
) -> AgentQuerySnapshot:
    record = snapshot.record
    if not record.source and not record.canonical:
        return AgentQuerySnapshot(
            dialect=snapshot.dialect,
            record=QueryRecord(source="", canonical="", profile_digest=None),
        )
    if snapshot.dialect != active_dialect:
        active_label = _dialect_label(active_dialect)
        stored_label = _dialect_label(snapshot.dialect)
        raise AgentQueryPersistenceError(
            "Saved Agents query was written by the "
            f"{stored_label} dialect, but {active_label} is active; "
            "switch the flag back or submit a new query to replace it."
        )
    if active_dialect == DIALECT_UNIFIED:
        current_digest = current_profile_digest(DIALECT_UNIFIED)
        if (
            record.profile_digest is not None
            and current_digest is not None
            and record.profile_digest != current_digest
        ):
            raise AgentQueryPersistenceError(
                "Saved Agents query no longer matches this query dialect; "
                "submit a new query to replace it."
            )
    elif record.profile_digest is not None:
        raise AgentQueryPersistenceError(
            "Saved Agents query has legacy dialect metadata it cannot use; "
            "submit a new query to replace it."
        )

    try:
        canonical = _canonical_for_dialect(record.source, active_dialect)
    except Exception as exc:
        raise AgentQueryPersistenceError(
            f"Saved Agents query no longer parses: {exc}; submit a new query to replace it."
        ) from exc
    if canonical != record.canonical:
        raise AgentQueryPersistenceError(
            "Saved Agents query no longer matches this query dialect; "
            "submit a new query to replace it."
        )
    return snapshot


def _canonical_for_dialect(source: str, dialect: AgentQueryDialect) -> str:
    if not source.strip():
        return ""
    if dialect == DIALECT_UNIFIED:
        from sase.ace.query.profile_reference import canonical_query_for_profile

        from .agent_live_query_engine import agents_live_query_profile

        return canonical_query_for_profile(source, agents_live_query_profile())
    if dialect == DIALECT_LEGACY:
        from sase.ace.agent_query import parse_agent_query, to_canonical_string

        return to_canonical_string(parse_agent_query(source))
    raise AgentQueryPersistenceError("unknown Agents query dialect")


def _serialize_snapshot(snapshot: AgentQuerySnapshot) -> bytes:
    payload = snapshot.to_wire()
    decoded = _decode_snapshot(payload)
    if decoded != snapshot:
        raise ValueError("Agents query snapshot failed validation")
    text = (
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_FILE_BYTES:
        raise ValueError("Agents query state exceeds maximum file size")
    return encoded


def _replace_state_file(source: Path, target: Path) -> None:
    os.replace(source, target)


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        log.debug(
            "Unable to fsync Agents query state directory: %s", path, exc_info=True
        )
    finally:
        os.close(fd)


def _dialect_label(dialect: str) -> str:
    if dialect == DIALECT_UNIFIED:
        return "unified"
    if dialect == DIALECT_LEGACY:
        return "legacy"
    return str(dialect)


__all__ = [
    "DIALECT_LEGACY",
    "DIALECT_UNIFIED",
    "FILENAME",
    "MAX_FILE_BYTES",
    "SCHEMA_VERSION",
    "AgentQueryDialect",
    "AgentQueryLoadResult",
    "AgentQueryPersistenceError",
    "AgentQuerySnapshot",
    "active_agent_query_dialect",
    "agent_query_state_path",
    "load_agent_query_snapshot",
    "make_agent_query_snapshot",
    "save_agent_query_snapshot",
]
