"""Execution-neutral parallel agent-family membership metadata."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path

FAMILY_MEMBERSHIP_ENV = "SASE_AGENT_FAMILY_MEMBERSHIP"


class FamilyMembershipError(RuntimeError):
    """Raised when a parallel family target or payload cannot be resolved."""


@dataclass(frozen=True)
class FamilyMembershipPlan:
    """Resolved family identity delivered from the launcher to one runner."""

    family_base: str
    root_timestamp: str
    root_artifacts_dir: str
    root_project_name: str
    role: str
    is_root: bool

    def identity_dependency(self, *, name: str | None = None) -> dict[str, str]:
        """Return the root's identity-pinned wait dependency payload."""
        return {
            "project_name": self.root_project_name,
            "timestamp": self.root_timestamp,
            "artifact_dir": self.root_artifacts_dir,
            "name": name or self.family_base,
        }


def encode_family_membership_plan(plan: FamilyMembershipPlan) -> str:
    """Encode *plan* for ``SASE_AGENT_FAMILY_MEMBERSHIP``."""
    return json.dumps(asdict(plan), sort_keys=True)


def consume_family_membership_plan_from_env() -> FamilyMembershipPlan | None:
    """Consume the host-only family payload so nested launches cannot inherit it."""
    raw = os.environ.pop(FAMILY_MEMBERSHIP_ENV, None)
    if not raw:
        return None
    return _decode_family_membership_plan(raw)


def resolve_existing_family_membership(
    target: str,
    *,
    role: str,
) -> FamilyMembershipPlan:
    """Resolve a directive-only member against the newest root on disk."""
    from sase.agent.names import (
        AgentNameTemplateError,
        find_agent_family,
        find_named_agent,
        resolve_agent_name_template_reference,
    )

    try:
        family_base = resolve_agent_name_template_reference(target)
    except AgentNameTemplateError as exc:
        raise FamilyMembershipError(
            f"Cannot resolve %family target '{target}': no matching agent exists"
        ) from exc

    family = find_agent_family(family_base)
    root_dir: Path | None = None
    root_timestamp: str | None = None
    if family is not None and family.root is not None:
        root_dir = family.root.artifacts_dir
        root_timestamp = family.root.timestamp
    else:
        exact = find_named_agent(family_base)
        if exact is not None:
            root_dir = Path(exact.artifacts_dir)
            root_timestamp = root_dir.name

    if root_dir is None or root_timestamp is None:
        raise FamilyMembershipError(
            f"Cannot resolve %family target '{target}': no family root or exact "
            "named agent exists"
        )

    return FamilyMembershipPlan(
        family_base=family_base,
        root_timestamp=root_timestamp,
        root_artifacts_dir=str(root_dir),
        root_project_name=_project_name_from_artifacts_dir(root_dir),
        role=role,
        is_root=False,
    )


def _decode_family_membership_plan(raw: str) -> FamilyMembershipPlan:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FamilyMembershipError(f"Invalid {FAMILY_MEMBERSHIP_ENV} payload") from exc
    if not isinstance(data, dict):
        raise FamilyMembershipError(f"Invalid {FAMILY_MEMBERSHIP_ENV} payload")

    required_strings = (
        "family_base",
        "root_timestamp",
        "root_artifacts_dir",
        "root_project_name",
        "role",
    )
    values: dict[str, str] = {}
    for key in required_strings:
        value = data.get(key)
        if not isinstance(value, str) or not value:
            raise FamilyMembershipError(
                f"Invalid {FAMILY_MEMBERSHIP_ENV} payload: missing {key}"
            )
        values[key] = value
    is_root = data.get("is_root")
    if not isinstance(is_root, bool):
        raise FamilyMembershipError(
            f"Invalid {FAMILY_MEMBERSHIP_ENV} payload: missing is_root"
        )
    return FamilyMembershipPlan(is_root=is_root, **values)


def _project_name_from_artifacts_dir(artifacts_dir: Path) -> str:
    try:
        return artifacts_dir.parents[2].name
    except IndexError as exc:
        raise FamilyMembershipError(
            f"Cannot derive project name from family root path '{artifacts_dir}'"
        ) from exc


__all__ = [
    "FAMILY_MEMBERSHIP_ENV",
    "FamilyMembershipError",
    "FamilyMembershipPlan",
    "consume_family_membership_plan_from_env",
    "encode_family_membership_plan",
    "resolve_existing_family_membership",
]
