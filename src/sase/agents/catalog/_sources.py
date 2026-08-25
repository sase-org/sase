"""Index-only, projected readers for the two enrichment sources.

Both readers are strictly read-only and never touch ``record_json`` (the
artifact index's ~117 MB blob column) or raw bundle JSON files, per the
epic's performance contract: build from the registry, the artifact index,
and the dismissed summary index only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3

from sase.ace.dismissed_bundle_index import DismissedBundleSummary
from sase.core.agent_scan_facade import default_agent_artifact_index_path
from sase.core.agent_scan_wire import AGENT_ARTIFACT_INDEX_SCHEMA_VERSION
from sase.core.dismissed_agents_facade import load_dismissed_bundle_summaries

# Only the columns the catalog's kind/attribute derivation actually needs.
# Never SELECT *, and never record_json (~117 MB across the whole table).
_ARTIFACT_INDEX_COLUMNS = (
    "artifact_dir",
    "project_name",
    "workflow_name",
    "agent_type",
    "cl_name",
    "model",
    "llm_provider",
    "status",
    "workflow_status",
    "hidden",
    "started_at",
    "finished_at",
    "retry_attempt",
    "agent_clan",
    "clan_tribe",
    "parent_timestamp",
    "retry_of_timestamp",
    "retried_as_timestamp",
    "retry_chain_root_timestamp",
)


@dataclass(frozen=True, slots=True)
class ArtifactIndexRecord:
    """One projected row from ``agent_artifacts``, keyed by ``artifact_dir``."""

    artifact_dir: str
    project_name: str | None
    workflow_name: str | None
    agent_type: str | None
    cl_name: str | None
    model: str | None
    llm_provider: str | None
    status: str | None
    workflow_status: str | None
    hidden: bool
    started_at: str | None
    finished_at: float | None
    retry_attempt: int | None
    agent_clan: str | None
    clan_tribe: str | None
    parent_timestamp: str | None
    retry_of_timestamp: str | None
    retried_as_timestamp: str | None
    retry_chain_root_timestamp: str | None


def load_artifact_index_projection(
    index_path: Path | str | None = None,
) -> dict[str, ArtifactIndexRecord]:
    """Return ``{artifact_dir: ArtifactIndexRecord}`` for the whole index.

    Returns an empty mapping (never raises) when the index is absent, the
    wrong schema version, or otherwise unreadable — the same "degrade a
    row, never drop it" posture the catalog applies everywhere else.
    """
    path = (
        Path(index_path)
        if index_path is not None
        else default_agent_artifact_index_path()
    )
    if not path.is_file():
        return {}
    columns_sql = ", ".join(_ARTIFACT_INDEX_COLUMNS)
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=0.25)
        try:
            connection.execute("PRAGMA busy_timeout=250")
            schema_row = connection.execute(
                "SELECT value FROM meta WHERE key = 'schema_version'"
            ).fetchone()
            if (
                schema_row is None
                or int(schema_row[0]) != AGENT_ARTIFACT_INDEX_SCHEMA_VERSION
            ):
                return {}
            rows = connection.execute(
                f"SELECT {columns_sql} FROM agent_artifacts"
            ).fetchall()
        finally:
            connection.close()
    except (OSError, sqlite3.DatabaseError, TypeError, ValueError):
        return {}

    records: dict[str, ArtifactIndexRecord] = {}
    for row in rows:
        values = dict(zip(_ARTIFACT_INDEX_COLUMNS, row, strict=True))
        artifact_dir = values["artifact_dir"]
        if not artifact_dir:
            continue
        records[artifact_dir] = ArtifactIndexRecord(
            artifact_dir=artifact_dir,
            project_name=values["project_name"],
            workflow_name=values["workflow_name"],
            agent_type=values["agent_type"],
            cl_name=values["cl_name"],
            model=values["model"],
            llm_provider=values["llm_provider"],
            status=values["status"],
            workflow_status=values["workflow_status"],
            hidden=bool(values["hidden"]),
            started_at=values["started_at"],
            finished_at=values["finished_at"],
            retry_attempt=values["retry_attempt"],
            agent_clan=values["agent_clan"],
            clan_tribe=values["clan_tribe"],
            parent_timestamp=values["parent_timestamp"],
            retry_of_timestamp=values["retry_of_timestamp"],
            retried_as_timestamp=values["retried_as_timestamp"],
            retry_chain_root_timestamp=values["retry_chain_root_timestamp"],
        )
    return records


def load_dismissed_top_level() -> list[DismissedBundleSummary]:
    """Return every top-level (non-workflow-child) dismissed bundle summary.

    ``top_level_only=True`` is load-bearing: the archive holds far more
    workflow-child bundles than top-level ones sharing the same
    ``raw_suffix``, and an unfiltered join would be many-to-one.
    """
    return load_dismissed_bundle_summaries(top_level_only=True)


def load_dismissed_child_fallback(
    raw_suffixes: frozenset[str],
) -> dict[str, DismissedBundleSummary]:
    """Return ``{raw_suffix: summary}`` for *raw_suffixes* with no top-level bundle.

    A small number of registry names are themselves workflow-child bundles
    with no top-level sibling under their own ``raw_suffix`` (their parent
    workflow's own bundle was pruned, or they were retried standalone).
    Rather than pay for an unfiltered archive scan (tens of thousands of
    rows) to find them, this targets exactly the leftover suffixes the
    top-level join did not match. A suffix with more than one matching
    bundle is genuinely ambiguous (observed once in 259 leftover suffixes
    on a live machine) and is dropped rather than guessed.
    """
    if not raw_suffixes:
        return {}
    summaries = load_dismissed_bundle_summaries(suffixes=set(raw_suffixes))
    by_suffix: dict[str, list[DismissedBundleSummary]] = {}
    for summary in summaries:
        by_suffix.setdefault(summary.raw_suffix, []).append(summary)
    return {
        suffix: matches[0] for suffix, matches in by_suffix.items() if len(matches) == 1
    }
