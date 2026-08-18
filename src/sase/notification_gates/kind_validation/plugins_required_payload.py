"""Structured payload parsing for PluginsRequired gate validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

from sase.notification_gates.models import GateError

_PLUGINS_REQUIRED_PAYLOAD_FIELDS = frozenset({"project", "project_label", "missing"})
_PLUGINS_REQUIRED_MISSING_FIELDS = frozenset(
    {"requirement", "name", "kind", "install_command", "message"}
)
_PLUGINS_REQUIRED_MISSING_KINDS = frozenset({"missing", "version_mismatch"})

PluginsRequiredMissingKind = Literal["missing", "version_mismatch"]


@dataclass(frozen=True)
class _PluginsRequiredMissing:
    """One unsatisfied required-plugin entry in a PluginsRequired payload."""

    requirement: str
    name: str
    kind: PluginsRequiredMissingKind
    install_command: str
    message: str


@dataclass(frozen=True)
class PluginsRequiredPayload:
    """The validated, structurally typed view of a required-plugin gate payload."""

    project: str
    project_label: str
    missing: tuple[_PluginsRequiredMissing, ...]


def parse_plugins_required_payload(
    payload: Mapping[str, Any],
) -> PluginsRequiredPayload:
    """Validate *payload* against the structured PluginsRequired contract."""
    from sase.core.paths import is_valid_sase_project_name

    if set(payload) != _PLUGINS_REQUIRED_PAYLOAD_FIELDS:
        raise GateError(
            "invalid_plugins_required_payload",
            "payload",
            "plugins required payload does not match the structured "
            "presentation contract",
        )
    project = payload.get("project")
    if not isinstance(project, str) or not is_valid_sase_project_name(project):
        raise GateError(
            "invalid_plugins_required_payload",
            "payload.project",
            "plugins required payload requires a canonical SASE project key",
        )
    project_label = payload.get("project_label")
    if not isinstance(project_label, str) or not project_label.strip():
        raise GateError(
            "invalid_plugins_required_payload",
            "payload.project_label",
            "plugins required payload requires a project label",
        )
    raw_missing = payload.get("missing")
    if not isinstance(raw_missing, list):
        raise GateError(
            "invalid_plugins_required_payload",
            "payload.missing",
            "plugins required payload missing must be a non-empty array",
        )
    if not raw_missing:
        raise GateError(
            "invalid_plugins_required_payload",
            "payload.missing",
            "plugins required payload missing must not be empty",
        )
    missing: list[_PluginsRequiredMissing] = []
    seen: set[tuple[str, str]] = set()
    for index, raw_item in enumerate(raw_missing):
        target = f"payload.missing[{index}]"
        if not isinstance(raw_item, Mapping) or set(raw_item) != (
            _PLUGINS_REQUIRED_MISSING_FIELDS
        ):
            raise GateError(
                "invalid_plugins_required_payload",
                target,
                "plugins required missing entry does not match the structured "
                "presentation contract",
            )
        kind = raw_item.get("kind")
        if kind not in _PLUGINS_REQUIRED_MISSING_KINDS:
            raise GateError(
                "invalid_plugins_required_payload",
                f"{target}.kind",
                "plugins required missing kind must be missing or version_mismatch",
            )
        requirement = _require_text(
            raw_item.get("requirement"), f"{target}.requirement"
        )
        name = _require_text(raw_item.get("name"), f"{target}.name")
        identity = (str(kind), requirement)
        if identity in seen:
            raise GateError(
                "invalid_plugins_required_payload",
                target,
                "plugins required payload has a duplicate missing entry",
            )
        seen.add(identity)
        missing.append(
            _PluginsRequiredMissing(
                requirement=requirement,
                name=name,
                kind=cast(PluginsRequiredMissingKind, kind),
                install_command=_require_text(
                    raw_item.get("install_command"), f"{target}.install_command"
                ),
                message=_require_text(raw_item.get("message"), f"{target}.message"),
            )
        )
    return PluginsRequiredPayload(
        project=project,
        project_label=project_label.strip(),
        missing=tuple(missing),
    )


def _require_text(value: object, target: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GateError(
            "invalid_plugins_required_payload",
            target,
            f"plugins required payload requires {target}",
        )
    return value


__all__ = [
    "PluginsRequiredPayload",
    "parse_plugins_required_payload",
]
