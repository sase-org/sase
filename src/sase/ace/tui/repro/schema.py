"""Schema objects for Agents-tab reproduction bundles."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

type AgentTypeValue = Literal["run", "workflow"]
type AgentIdentity = tuple[AgentTypeValue, str, str | None]
type JsonScalar = str | int | float | bool | None

SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS = frozenset({1, SCHEMA_VERSION})


def _expect_mapping(value: Any, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return value


def _expect_list(value: Any, *, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    return value


def _optional_str(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string or null")
    return value


def _optional_int(value: Any, *, field_name: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer or null")
    return value


def _bool(value: Any, *, field_name: str, default: bool = False) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _agent_type(value: Any, *, field_name: str) -> AgentTypeValue:
    if value == "run" or value == "workflow":
        return value
    raise ValueError(f"{field_name} must be 'run' or 'workflow'")


def _identity_from_json(value: Any, *, field_name: str = "identity") -> AgentIdentity:
    """Parse a JSON identity tuple.

    The JSON form is ``[agent_type, cl_name, raw_suffix]`` so bundles stay
    language-neutral while Python callers get tuple identities matching
    ``Agent.identity`` semantics.
    """

    items = _expect_list(value, field_name=field_name)
    if len(items) != 3:
        raise ValueError(f"{field_name} must have exactly three items")
    agent_type = _agent_type(items[0], field_name=f"{field_name}[0]")
    cl_name = items[1]
    if not isinstance(cl_name, str):
        raise ValueError(f"{field_name}[1] must be a string")
    raw_suffix = _optional_str(items[2], field_name=f"{field_name}[2]")
    return (agent_type, cl_name, raw_suffix)


def identity_to_json(identity: AgentIdentity) -> list[str | None]:
    return [identity[0], identity[1], identity[2]]


def _identities_from_json(value: Any, *, field_name: str) -> list[AgentIdentity]:
    return [
        _identity_from_json(item, field_name=f"{field_name}[{index}]")
        for index, item in enumerate(_expect_list(value, field_name=field_name))
    ]


def _identities_by_step_from_json(value: Any) -> dict[str, list[AgentIdentity]]:
    if value is None:
        return {}
    raw = _expect_mapping(value, field_name="expected_visible_identities_by_step")
    return {
        step_id: _identities_from_json(
            identities,
            field_name=f"expected_visible_identities_by_step[{step_id}]",
        )
        for step_id, identities in raw.items()
    }


@dataclass(frozen=True)
class ReproManifest:
    """Bundle metadata and safety labels."""

    schema_version: int
    name: str
    created_at: str
    source: str
    commit_safe: bool
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReproManifest:
        return cls(
            schema_version=int(data.get("schema_version", 0)),
            name=str(data.get("name", "")),
            created_at=str(data.get("created_at", "")),
            source=str(data.get("source", "")),
            commit_safe=_bool(data.get("commit_safe"), field_name="commit_safe"),
            description=str(data.get("description", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "created_at": self.created_at,
            "source": self.source,
            "commit_safe": self.commit_safe,
            "description": self.description,
        }


@dataclass(frozen=True)
class ReproLoadState:
    """Serialized subset of ``AgentLoadState`` needed for replay."""

    tier: Literal["tier1", "tier2"]
    complete_history: bool
    complete_visible_inbox: bool
    artifact_source: Literal["artifact_index", "source_scan", "artifact_delta"]
    used_artifact_index: bool
    index_error: str | None = None
    repair_recommended: bool = False
    repair_reason: str | None = None
    truncated: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReproLoadState:
        tier = data.get("tier")
        if tier != "tier1" and tier != "tier2":
            raise ValueError("load_state.tier must be 'tier1' or 'tier2'")
        source = data.get("artifact_source")
        if source not in {"artifact_index", "source_scan", "artifact_delta"}:
            raise ValueError(
                "load_state.artifact_source must be 'artifact_index', "
                "'source_scan', or 'artifact_delta'"
            )
        return cls(
            tier=tier,
            complete_history=_bool(
                data.get("complete_history"), field_name="complete_history"
            ),
            complete_visible_inbox=_bool(
                data.get("complete_visible_inbox", data.get("complete_history")),
                field_name="complete_visible_inbox",
            ),
            artifact_source=source,
            used_artifact_index=_bool(
                data.get("used_artifact_index"), field_name="used_artifact_index"
            ),
            index_error=_optional_str(
                data.get("index_error"), field_name="index_error"
            ),
            repair_recommended=_bool(
                data.get("repair_recommended", False),
                field_name="repair_recommended",
            ),
            repair_reason=_optional_str(
                data.get("repair_reason"), field_name="repair_reason"
            ),
            truncated=_bool(data.get("truncated", False), field_name="truncated"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "complete_history": self.complete_history,
            "complete_visible_inbox": self.complete_visible_inbox,
            "artifact_source": self.artifact_source,
            "used_artifact_index": self.used_artifact_index,
            "index_error": self.index_error,
            "repair_recommended": self.repair_recommended,
            "repair_reason": self.repair_reason,
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class ReproAgentRow:
    """Commit-safe row summary for Agents-tab replay and invariants."""

    agent_type: AgentTypeValue
    cl_name: str
    raw_suffix: str | None
    status: str
    parent_timestamp: str | None = None
    parent_workflow: str | None = None
    workflow: str | None = None
    appears_as_agent: bool = False
    step_type: str | None = None
    pid: int | None = None
    workspace_num: int | None = None
    agent_name: str | None = None
    tribe: str | None = None
    metadata: dict[str, JsonScalar] = field(default_factory=dict)

    @property
    def identity(self) -> AgentIdentity:
        return (self.agent_type, self.cl_name, self.raw_suffix)

    @property
    def is_child(self) -> bool:
        return self.parent_timestamp is not None or self.parent_workflow is not None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReproAgentRow:
        metadata = data.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError("agent row metadata must be an object")
        return cls(
            agent_type=_agent_type(data.get("agent_type"), field_name="agent_type"),
            cl_name=str(data.get("cl_name", "")),
            raw_suffix=_optional_str(data.get("raw_suffix"), field_name="raw_suffix"),
            status=str(data.get("status", "")),
            parent_timestamp=_optional_str(
                data.get("parent_timestamp"), field_name="parent_timestamp"
            ),
            parent_workflow=_optional_str(
                data.get("parent_workflow"), field_name="parent_workflow"
            ),
            workflow=_optional_str(data.get("workflow"), field_name="workflow"),
            appears_as_agent=_bool(
                data.get("appears_as_agent"), field_name="appears_as_agent"
            ),
            step_type=_optional_str(data.get("step_type"), field_name="step_type"),
            pid=_optional_int(data.get("pid"), field_name="pid"),
            workspace_num=_optional_int(
                data.get("workspace_num"), field_name="workspace_num"
            ),
            agent_name=_optional_str(data.get("agent_name"), field_name="agent_name"),
            tribe=_optional_str(
                data.get("tribe") if "tribe" in data else data.get("tag"),
                field_name="tribe",
            ),
            metadata={
                str(key): value
                for key, value in metadata.items()
                if value is None or isinstance(value, str | int | float | bool)
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_type": self.agent_type,
            "cl_name": self.cl_name,
            "raw_suffix": self.raw_suffix,
            "status": self.status,
            "parent_timestamp": self.parent_timestamp,
            "parent_workflow": self.parent_workflow,
            "workflow": self.workflow,
            "appears_as_agent": self.appears_as_agent,
            "step_type": self.step_type,
            "pid": self.pid,
            "workspace_num": self.workspace_num,
            "agent_name": self.agent_name,
            "tribe": self.tribe,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ReproSelectionFallback:
    """Intentional selection replacement after refresh."""

    from_identity: AgentIdentity | None
    to_identity: AgentIdentity | None
    reason: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReproSelectionFallback:
        raw_from = data.get("from_identity")
        raw_to = data.get("to_identity")
        return cls(
            from_identity=(
                None
                if raw_from is None
                else _identity_from_json(raw_from, field_name="from_identity")
            ),
            to_identity=(
                None
                if raw_to is None
                else _identity_from_json(raw_to, field_name="to_identity")
            ),
            reason=str(data.get("reason", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_identity": (
                None
                if self.from_identity is None
                else identity_to_json(self.from_identity)
            ),
            "to_identity": (
                None if self.to_identity is None else identity_to_json(self.to_identity)
            ),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ReproAppState:
    """Structured Agents-tab projection after one load/apply cycle."""

    visible_identities: list[AgentIdentity]
    selected_identity: AgentIdentity | None = None
    dismissed_identities: list[AgentIdentity] = field(default_factory=list)
    flattened_parent_timestamps: list[str] = field(default_factory=list)
    agents_seen_complete_history: bool = False
    selection_fallback: ReproSelectionFallback | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReproAppState:
        raw_selected = data.get("selected_identity")
        raw_fallback = data.get("selection_fallback")
        return cls(
            visible_identities=_identities_from_json(
                data.get("visible_identities", []),
                field_name="visible_identities",
            ),
            selected_identity=(
                None
                if raw_selected is None
                else _identity_from_json(raw_selected, field_name="selected_identity")
            ),
            dismissed_identities=_identities_from_json(
                data.get("dismissed_identities", []),
                field_name="dismissed_identities",
            ),
            flattened_parent_timestamps=[
                str(item)
                for item in _expect_list(
                    data.get("flattened_parent_timestamps", []),
                    field_name="flattened_parent_timestamps",
                )
            ],
            agents_seen_complete_history=_bool(
                data.get("agents_seen_complete_history"),
                field_name="agents_seen_complete_history",
            ),
            selection_fallback=(
                None
                if raw_fallback is None
                else ReproSelectionFallback.from_dict(
                    _expect_mapping(raw_fallback, field_name="selection_fallback")
                )
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "visible_identities": [
                identity_to_json(identity) for identity in self.visible_identities
            ],
            "selected_identity": (
                None
                if self.selected_identity is None
                else identity_to_json(self.selected_identity)
            ),
            "dismissed_identities": [
                identity_to_json(identity) for identity in self.dismissed_identities
            ],
            "flattened_parent_timestamps": list(self.flattened_parent_timestamps),
            "agents_seen_complete_history": self.agents_seen_complete_history,
            "selection_fallback": (
                None
                if self.selection_fallback is None
                else self.selection_fallback.to_dict()
            ),
        }


@dataclass(frozen=True)
class ReproScreen:
    """Optional screen text and screenshot references for later replay phases."""

    text: str = ""
    svg_path: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReproScreen:
        return cls(
            text=str(data.get("text", "")),
            svg_path=_optional_str(data.get("svg_path"), field_name="svg_path"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "svg_path": self.svg_path}


@dataclass(frozen=True)
class ReproLoadStep:
    """One loader/apply snapshot in an Agents-tab reproduction."""

    step_id: str
    label: str
    load_state: ReproLoadState
    agent_rows: list[ReproAgentRow]
    app_state: ReproAppState
    screen: ReproScreen = field(default_factory=ReproScreen)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReproLoadStep:
        return cls(
            step_id=str(data.get("step_id", "")),
            label=str(data.get("label", "")),
            load_state=ReproLoadState.from_dict(
                _expect_mapping(data.get("load_state", {}), field_name="load_state")
            ),
            agent_rows=[
                ReproAgentRow.from_dict(
                    _expect_mapping(item, field_name=f"agent_rows[{index}]")
                )
                for index, item in enumerate(
                    _expect_list(data.get("agent_rows", []), field_name="agent_rows")
                )
            ],
            app_state=ReproAppState.from_dict(
                _expect_mapping(data.get("app_state", {}), field_name="app_state")
            ),
            screen=ReproScreen.from_dict(
                _expect_mapping(data.get("screen", {}), field_name="screen")
            ),
            metadata=dict(
                _expect_mapping(data.get("metadata", {}), field_name="metadata")
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "label": self.label,
            "load_state": self.load_state.to_dict(),
            "agent_rows": [row.to_dict() for row in self.agent_rows],
            "app_state": self.app_state.to_dict(),
            "screen": self.screen.to_dict(),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ReproAssertions:
    """Expected stable projections used by tests and replay verdicts."""

    expected_visible_identities_by_step: dict[str, list[AgentIdentity]] = field(
        default_factory=dict
    )
    stable_step_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReproAssertions:
        return cls(
            expected_visible_identities_by_step=_identities_by_step_from_json(
                data.get("expected_visible_identities_by_step")
            ),
            stable_step_ids=[
                str(item)
                for item in _expect_list(
                    data.get("stable_step_ids", []), field_name="stable_step_ids"
                )
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_visible_identities_by_step": {
                step_id: [identity_to_json(identity) for identity in identities]
                for step_id, identities in self.expected_visible_identities_by_step.items()
            },
            "stable_step_ids": list(self.stable_step_ids),
        }


@dataclass(frozen=True)
class ReproBundle:
    """Complete MVP reproduction bundle."""

    manifest: ReproManifest
    load_steps: list[ReproLoadStep]
    assertions: ReproAssertions = field(default_factory=ReproAssertions)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReproBundle:
        manifest = ReproManifest.from_dict(
            _expect_mapping(data.get("manifest", {}), field_name="manifest")
        )
        if manifest.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"unsupported repro schema_version {manifest.schema_version}"
            )
        return cls(
            manifest=manifest,
            load_steps=[
                ReproLoadStep.from_dict(
                    _expect_mapping(item, field_name=f"load_steps[{index}]")
                )
                for index, item in enumerate(
                    _expect_list(data.get("load_steps", []), field_name="load_steps")
                )
            ],
            assertions=ReproAssertions.from_dict(
                _expect_mapping(data.get("assertions", {}), field_name="assertions")
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest.to_dict(),
            "load_steps": [step.to_dict() for step in self.load_steps],
            "assertions": self.assertions.to_dict(),
        }


def load_bundle(path: str | Path) -> ReproBundle:
    """Load and validate a repro bundle from JSON."""

    with Path(path).open(encoding="utf-8") as handle:
        data = json.load(handle)
    return ReproBundle.from_dict(_expect_mapping(data, field_name="bundle"))
