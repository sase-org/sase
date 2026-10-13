"""Python boundary for immutable agent archive contracts."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.core.rust import require_rust_binding

if TYPE_CHECKING:
    from pathlib import Path

    from sase.ace.query_profile import CompiledQueryProfile

ARCHIVE_VISIBILITIES = frozenset({"hidden", "visible", "pinned"})


@dataclass(frozen=True, slots=True)
class _AgentArchiveKey:
    source_username: str
    source_machine: str
    source_run_id: str

    def to_json_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _AgentArchiveCapabilityFacts:
    has_metadata: bool
    has_state: bool
    has_commits: bool
    loader_reconstructible: bool
    has_prompt: bool
    has_model: bool
    has_llm_provider: bool
    has_reasoning_effort: bool

    def to_json_dict(self) -> dict[str, bool]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AgentArchiveCapabilities:
    historically_viewable: bool
    durably_revivable: bool
    restartable: bool
    missing_requirements: tuple[str, ...] = ()

    def to_json_dict(self) -> dict[str, object]:
        return {
            "historically_viewable": self.historically_viewable,
            "durably_revivable": self.durably_revivable,
            "restartable": self.restartable,
            "missing_requirements": list(self.missing_requirements),
        }


def _validate_archive_key(
    key: _AgentArchiveKey | Mapping[str, Any],
) -> _AgentArchiveKey:
    payload = key.to_json_dict() if isinstance(key, _AgentArchiveKey) else dict(key)
    binding = require_rust_binding("validate_agent_archive_key")
    return _key_from_mapping(binding(payload))


def validate_archive_visibility(visibility: str) -> str:
    binding = require_rust_binding("validate_agent_archive_visibility")
    payload = binding({"visibility": visibility})
    value = payload.get("visibility")
    if not isinstance(value, str):
        raise ValueError("Rust archive visibility validator returned invalid wire")
    return value


def _derive_archive_capabilities(
    facts: _AgentArchiveCapabilityFacts | Mapping[str, Any],
    *,
    asserted: AgentArchiveCapabilities | Mapping[str, Any] | None = None,
) -> AgentArchiveCapabilities:
    fact_payload = (
        facts.to_json_dict()
        if isinstance(facts, _AgentArchiveCapabilityFacts)
        else dict(facts)
    )
    asserted_payload: Mapping[str, Any] | None
    if isinstance(asserted, AgentArchiveCapabilities):
        asserted_payload = asserted.to_json_dict()
    else:
        asserted_payload = asserted
    binding = require_rust_binding("validate_agent_archive_capabilities")
    payload = binding({"facts": fact_payload, "asserted": asserted_payload})
    return _capabilities_from_mapping(payload)


def archive_key_from_owner(
    owner: AgentOwnerIdentity,
    source_run_id: str,
) -> _AgentArchiveKey:
    return _validate_archive_key(
        _AgentArchiveKey(owner.username, owner.machine_name, source_run_id)
    )


def archive_key_from_bundle(bundle: Mapping[str, Any]) -> _AgentArchiveKey | None:
    username = _text(bundle.get("source_username"))
    machine = _text(bundle.get("source_machine"))
    run_id = _text(bundle.get("source_run_id"))
    if username and machine and run_id:
        return _validate_archive_key(_AgentArchiveKey(username, machine, run_id))

    owner = bundle.get("imported_source_owner")
    if isinstance(owner, Mapping):
        username = _text(owner.get("username"))
        machine = _text(owner.get("machine_name"))
        run_id = _text(bundle.get("imported_source_run_id"))
        step_output = bundle.get("step_output")
        if run_id is None and isinstance(step_output, Mapping):
            run_id = _text(step_output.get("imported_source_run_id"))
        if username and machine and run_id:
            return _validate_archive_key(_AgentArchiveKey(username, machine, run_id))
    return None


def capabilities_from_v2_run(
    metadata: Mapping[str, Any],
    file_kinds: Collection[str],
    *,
    asserted: AgentArchiveCapabilities | Mapping[str, Any] | None = None,
) -> AgentArchiveCapabilities:
    return _derive_archive_capabilities(
        _AgentArchiveCapabilityFacts(
            has_metadata="meta" in file_kinds,
            has_state="state" in file_kinds,
            has_commits="commits" in file_kinds,
            loader_reconstructible={"meta", "state", "commits"}.issubset(file_kinds),
            has_prompt="prompt" in file_kinds,
            has_model=bool(_text(metadata.get("model"))),
            has_llm_provider=bool(_text(metadata.get("llm_provider"))),
            has_reasoning_effort=bool(_text(metadata.get("reasoning_effort"))),
        ),
        asserted=asserted,
    )


def capabilities_from_bundle(bundle: Mapping[str, Any]) -> AgentArchiveCapabilities:
    asserted = _asserted_capabilities(bundle)
    facts = _AgentArchiveCapabilityFacts(
        has_metadata=bool(
            _text(bundle.get("raw_suffix"))
            and (
                _text(bundle.get("agent_name"))
                or _text(bundle.get("cl_name"))
                or _text(bundle.get("patch_name"))
            )
        ),
        has_state=bool(
            _text(bundle.get("status"))
            and (
                _text(bundle.get("start_time"))
                or _text(bundle.get("stop_time"))
                or _text(bundle.get("raw_suffix"))
            )
        ),
        has_commits=True,
        loader_reconstructible=bool(_text(bundle.get("raw_suffix"))),
        has_prompt=any(
            isinstance(bundle.get(key), str) and bool(bundle.get(key))
            for key in ("raw_xprompt", "raw_prompt", "prompt")
        ),
        has_model=bool(_text(bundle.get("model"))),
        has_llm_provider=bool(_text(bundle.get("llm_provider"))),
        has_reasoning_effort=bool(_text(bundle.get("reasoning_effort"))),
    )
    return _derive_archive_capabilities(facts, asserted=asserted)


def _asserted_capabilities(
    bundle: Mapping[str, Any],
) -> AgentArchiveCapabilities | None:
    value = bundle.get("archive_capabilities")
    if isinstance(value, Mapping):
        return _capabilities_from_mapping(value)
    return None


def _key_from_mapping(value: Mapping[str, Any]) -> _AgentArchiveKey:
    return _AgentArchiveKey(
        source_username=str(value["source_username"]),
        source_machine=str(value["source_machine"]),
        source_run_id=str(value["source_run_id"]),
    )


def _capabilities_from_mapping(value: Mapping[str, Any]) -> AgentArchiveCapabilities:
    missing = value.get("missing_requirements") or ()
    if not isinstance(missing, (list, tuple)) or not all(
        isinstance(item, str) for item in missing
    ):
        raise ValueError("archive capability missing_requirements must be strings")
    return AgentArchiveCapabilities(
        historically_viewable=bool(value.get("historically_viewable")),
        durably_revivable=bool(value.get("durably_revivable")),
        restartable=bool(value.get("restartable")),
        missing_requirements=tuple(missing),
    )


def _text(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


@dataclass(frozen=True, slots=True)
class AgentArchiveCorpus:
    """An immutable compiled archive corpus handle.

    Wraps the ``compile_agent_archive_corpus`` Rust handle. Query methods
    canonicalize relative dates in Python first, the same way
    :mod:`sase.core.query_profile_corpus_facade` does, then hand the
    already-literal query to Rust for batch matching.
    """

    handle: Any
    status: str
    status_details: Mapping[str, Any]
    timezone: str

    def summary(
        self,
        query: str,
        *,
        group_by: str,
        profile: CompiledQueryProfile | None = None,
    ) -> dict[str, Any]:
        """Group matching presentation roots, omitting empty groups."""
        resolved = profile if profile is not None else agents_archive_profile()
        binding = require_rust_binding("summarize_agent_archive_corpus")
        return binding(
            self.handle,
            {
                "query": _canonical_archive_query(query, resolved),
                "profile": resolved.to_wire(),
                "group_by": group_by,
            },
        )

    def rows(
        self,
        query: str,
        *,
        group_by: str,
        group_key: str,
        offset: int,
        limit: int,
        expanded_container_keys: Collection[str] = (),
        profile: CompiledQueryProfile | None = None,
    ) -> dict[str, Any]:
        """Return one offset/limit window of light rows inside *group_key*."""
        resolved = profile if profile is not None else agents_archive_profile()
        binding = require_rust_binding("rows_agent_archive_corpus")
        return binding(
            self.handle,
            {
                "query": _canonical_archive_query(query, resolved),
                "profile": resolved.to_wire(),
                "group_by": group_by,
                "group_key": group_key,
                "offset": offset,
                "limit": limit,
                "expanded_container_keys": list(expanded_container_keys),
            },
        )

    def lookup(self, name: str) -> dict[str, Any] | None:
        """Resolve one exact archive name to its owner's light row, if any."""
        binding = require_rust_binding("lookup_agent_archive_corpus")
        payload = binding(self.handle, {"name": name})
        row = payload.get("row")
        return dict(row) if isinstance(row, Mapping) else None

    def count(
        self,
        query: str,
        *,
        profile: CompiledQueryProfile | None = None,
    ) -> int:
        """Count matching presentation roots for *query*."""
        resolved = profile if profile is not None else agents_archive_profile()
        binding = require_rust_binding("count_agent_archive_corpus")
        payload = binding(
            self.handle,
            {
                "query": _canonical_archive_query(query, resolved),
                "profile": resolved.to_wire(),
            },
        )
        return int(payload.get("count", 0))


def agents_archive_profile() -> CompiledQueryProfile:
    """Compile the current ``agents-archive`` query profile."""
    from sase.ace.query_profile import compile_query_profile
    from sase.ace.query_profile.profiles._agents_archive import (
        agents_archive_query_schema,
    )

    return compile_query_profile(agents_archive_query_schema())


def compile_agent_archive_corpus(
    *,
    root: Path | str,
    index_status: Mapping[str, Any],
    timezone: str | None = None,
    link_facets: Mapping[str, Any] | None = None,
) -> AgentArchiveCorpus:
    """Compile the v3 archive index at *root* into an immutable corpus.

    *index_status* is the ``AgentArchiveIndexProbeStatusWire`` mapping the
    caller already probed (``missing``, ``rebuilding`` with a count, or
    ``ok``). This never creates or rebuilds the index; a missing file
    compiles to an empty corpus.
    """
    binding = require_rust_binding("compile_agent_archive_corpus")
    from sase.ace.dismissed_bundle_index._lock import dismissed_index_operation_lock

    with dismissed_index_operation_lock():
        handle = binding(
            {
                "root": str(root),
                "index_status": dict(index_status),
                "timezone": timezone or _default_archive_timezone_name(),
                "link_facets": _link_facets_wire(link_facets),
            }
        )
    status_details = handle.status()
    status_name = (
        status_details.get("status") if isinstance(status_details, Mapping) else None
    )
    details = dict(status_details) if isinstance(status_details, Mapping) else {}
    return AgentArchiveCorpus(
        handle=handle,
        status=str(status_name or "missing"),
        status_details=details,
        timezone=str(handle.timezone or ""),
    )


def _canonical_archive_query(query: str, profile: CompiledQueryProfile) -> str:
    from sase.ace.query.profile_reference import canonical_query_for_profile

    return canonical_query_for_profile(query, profile)


def _default_archive_timezone_name() -> str:
    from sase.core.time import get_timezone, local_timezone_name

    name = local_timezone_name()
    if name:
        return name
    return f"UTC{datetime.now(get_timezone()).strftime('%z')}"


def _link_facets_wire(
    link_facets: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if not link_facets:
        return {}
    wire: dict[str, dict[str, Any]] = {}
    for name, facets in link_facets.items():
        if isinstance(facets, Mapping):
            relations = facets.get("relations", ())
            artifacts = facets.get("artifacts", ())
            count = facets.get("count", 0)
        else:
            relations = facets.relations
            artifacts = facets.artifacts
            count = facets.count
        wire[str(name)] = {
            "relations": [str(value) for value in relations],
            "artifacts": [str(value) for value in artifacts],
            "count": int(count),
        }
    return wire


__all__ = [
    "ARCHIVE_VISIBILITIES",
    "AgentArchiveCapabilities",
    "AgentArchiveCorpus",
    "agents_archive_profile",
    "archive_key_from_bundle",
    "archive_key_from_owner",
    "capabilities_from_bundle",
    "capabilities_from_v2_run",
    "compile_agent_archive_corpus",
    "validate_archive_visibility",
]
