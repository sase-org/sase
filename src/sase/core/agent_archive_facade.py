"""Python boundary for immutable agent archive contracts."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.core.rust import require_rust_binding

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


__all__ = [
    "ARCHIVE_VISIBILITIES",
    "AgentArchiveCapabilities",
    "archive_key_from_bundle",
    "archive_key_from_owner",
    "capabilities_from_bundle",
    "capabilities_from_v2_run",
    "validate_archive_visibility",
]
