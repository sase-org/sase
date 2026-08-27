"""Additive shell block model for v3 notification gate requests."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

from sase.notification_gates.model_validation import (
    GateError,
    json_object,
    reject_unknown_fields,
    validate_color,
)
from sase.plan_chain import canonical_plan_chain_suffix
from sase.shells.status import clamp_shell_status

DEFAULT_GATE_SHELL_PENDING_STATUS = "GATE"
DEFAULT_GATE_SHELL_SETTLED_STATUS = "GATED"
GATE_SHELL_DEFAULT_TIMEOUT_SECONDS = 24 * 60 * 60.0
GATE_SHELL_STATUS_MAX_CHARS = 20
GATE_SHELL_STATUS_ELLIPSIS = "\u2026"

GATE_SHELL_WORKSPACES = frozenset({"inherit", "release"})
GATE_SHELL_NEXT_FORKS = frozenset({"family", "shell", "none"})
GATE_SHELL_NEXT_OUTPUTS = frozenset({"none", "results", "tail", "file"})
GATE_SHELL_RESERVED_BRANCHES = frozenset({"timeout", "stopped", "failed"})
SUBSET_BRANCH_GATE_KINDS = frozenset({"epic_plan", "plan"})
_ROLE_RE = re.compile(r"^[A-Za-z0-9_]+$")

_DEFAULT_ACCENTS: tuple[str, ...] = (
    "#FEA775",
    "#F8AD08",
    "#CCBF08",
    "#81D005",
    "#0BD68B",
    "#00D2C4",
    "#0BCDEC",
    "#6FC4FF",
    "#A1BAFF",
    "#C4B0FE",
    "#F39CFE",
    "#FF9ECD",
)


@dataclass(frozen=True, slots=True)
class GateShellNext:
    """Follow-up policy declared for a gate shell or one terminal branch."""

    prompt: str | None = None
    output: tuple[str, ...] = ("results",)
    fork: str = "family"
    model: str | None = None
    suffix: str | None = None
    role: str | None = None
    raw_prompt: bool = False

    @classmethod
    def from_mapping(
        cls,
        value: object,
        *,
        target: str,
        inherited: GateShellNext | None = None,
    ) -> GateShellNext:
        if value is None:
            return inherited or cls()
        data = json_object(value, target)
        reject_unknown_fields(
            data,
            {
                "prompt",
                "output",
                "fork",
                "model",
                "suffix",
                "role",
                "raw_prompt",
            },
            target,
        )
        base = inherited or cls()
        prompt = _optional_str(data.get("prompt", base.prompt), f"{target}.prompt")
        model = _optional_str(data.get("model", base.model), f"{target}.model")
        suffix = _optional_str(data.get("suffix", base.suffix), f"{target}.suffix")
        role = _optional_role(data.get("role", base.role), f"{target}.role")
        raw_prompt = _raw_prompt(data.get("raw_prompt", base.raw_prompt), target)
        fork = data.get("fork", base.fork)
        if fork not in GATE_SHELL_NEXT_FORKS:
            raise GateError(
                "invalid_shell",
                f"{target}.fork",
                "next.fork must be family, shell, or none",
            )
        output = _next_output(data.get("output", list(base.output)), f"{target}.output")
        return cls(
            prompt=prompt,
            output=output,
            fork=str(fork),
            model=model,
            suffix=suffix,
            role=role,
            raw_prompt=raw_prompt,
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "prompt": self.prompt,
            "output": list(self.output),
            "fork": self.fork,
            "model": self.model,
        }
        if self.suffix is not None:
            data["suffix"] = self.suffix
        if self.role is not None:
            data["role"] = self.role
        if self.raw_prompt:
            data["raw_prompt"] = True
        return data


_BRANCH_NEXT_FIELDS = (
    "prompt",
    "output",
    "fork",
    "model",
    "suffix",
    "role",
    "raw_prompt",
)


@dataclass(frozen=True, slots=True)
class GateShellBranchSpec:
    """Per-terminal-branch gate-shell policy.

    ``prompt``/``output``/``fork``/``model`` accept the same shape as the
    top-level ``shell.next`` block, but flattened directly onto the branch
    alongside ``status``/``accent`` -- there is no nested ``next`` object at
    the branch level. A field a branch omits inherits the top-level
    ``shell.next`` value for that field; an explicit ``"prompt": null``
    suppresses follow-up even when the top level declares one.
    """

    status: str | None = None
    accent: str | None = None
    prompt: str | None = None
    output: tuple[str, ...] = ("results",)
    fork: str = "family"
    model: str | None = None
    suffix: str | None = None
    role: str | None = None
    raw_prompt: bool = False

    @classmethod
    def from_mapping(
        cls,
        value: object,
        *,
        target: str,
        inherited_next: GateShellNext,
    ) -> GateShellBranchSpec:
        data = json_object(value, target)
        reject_unknown_fields(data, {"status", "accent", *_BRANCH_NEXT_FIELDS}, target)
        next_data = {key: data[key] for key in _BRANCH_NEXT_FIELDS if key in data}
        next_policy = GateShellNext.from_mapping(
            next_data, target=target, inherited=inherited_next
        )
        return cls(
            status=_optional_status(data.get("status"), f"{target}.status"),
            accent=validate_color(data.get("accent"), f"{target}.accent"),
            prompt=next_policy.prompt,
            output=next_policy.output,
            fork=next_policy.fork,
            model=next_policy.model,
            suffix=next_policy.suffix,
            role=next_policy.role,
            raw_prompt=next_policy.raw_prompt,
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "status": self.status,
            "accent": self.accent,
            "prompt": self.prompt,
            "output": list(self.output),
            "fork": self.fork,
            "model": self.model,
        }
        if self.suffix is not None:
            data["suffix"] = self.suffix
        if self.role is not None:
            data["role"] = self.role
        if self.raw_prompt:
            data["raw_prompt"] = True
        return data


@dataclass(frozen=True, slots=True)
class GateShellSpec:
    """Validated additive ``shell`` block for a v3 gate request."""

    suffix: str | None = None
    pending_status: str = DEFAULT_GATE_SHELL_PENDING_STATUS
    settled_status: str = DEFAULT_GATE_SHELL_SETTLED_STATUS
    accent: str = field(default_factory=lambda: _default_accent("GATE\x1fGATED"))
    workspace: str = "inherit"
    next: GateShellNext = field(default_factory=GateShellNext)
    branches: dict[str, GateShellBranchSpec] = field(default_factory=dict)

    @classmethod
    def from_mapping(
        cls,
        value: object,
        *,
        branches: tuple[tuple[str, ...], ...],
        allow_branch_subsets: bool = False,
    ) -> GateShellSpec:
        data = json_object(value, "shell")
        reject_unknown_fields(
            data,
            {
                "suffix",
                "pending_status",
                "settled_status",
                "accent",
                "workspace",
                "next",
                "branches",
            },
            "shell",
        )
        pending_status = _status(
            data.get("pending_status", DEFAULT_GATE_SHELL_PENDING_STATUS),
            "shell.pending_status",
        )
        settled_status = _status(
            data.get("settled_status", DEFAULT_GATE_SHELL_SETTLED_STATUS),
            "shell.settled_status",
        )
        next_policy = GateShellNext.from_mapping(data.get("next"), target="shell.next")
        workspace = data.get("workspace", "inherit")
        if workspace not in GATE_SHELL_WORKSPACES:
            raise GateError(
                "invalid_shell",
                "shell.workspace",
                "shell.workspace must be inherit or release",
            )
        suffix = _suffix(data.get("suffix"))
        accent = validate_color(data.get("accent"), "shell.accent") or _default_accent(
            f"{pending_status.upper()}\x1f{settled_status.upper()}"
        )
        return cls(
            suffix=suffix,
            pending_status=pending_status,
            settled_status=settled_status,
            accent=accent,
            workspace=str(workspace),
            next=next_policy,
            branches=_branches(
                data.get("branches", {}),
                valid_branch_keys=_valid_branch_keys(
                    branches,
                    allow_subsets=allow_branch_subsets,
                ),
                inherited_next=next_policy,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "suffix": self.suffix,
            "pending_status": self.pending_status,
            "settled_status": self.settled_status,
            "accent": self.accent,
            "workspace": self.workspace,
            "next": self.next.to_dict(),
            "branches": {
                key: branch.to_dict()
                for key, branch in sorted(
                    self.branches.items(), key=lambda item: item[0]
                )
            },
        }


def _valid_branch_keys(
    branches: tuple[tuple[str, ...], ...],
    *,
    allow_subsets: bool,
) -> frozenset[str]:
    keys: set[str] = set()
    for branch in branches:
        if allow_subsets:
            for count in range(1, len(branch) + 1):
                keys.update("+".join(subset) for subset in combinations(branch, count))
        else:
            keys.add("+".join(branch))
    return frozenset(keys) | GATE_SHELL_RESERVED_BRANCHES


def subset_branches_allowed(kind: object) -> bool:
    """Return whether *kind* may declare subset branch keys in its shell block."""
    return isinstance(kind, str) and kind in SUBSET_BRANCH_GATE_KINDS


def _branches(
    value: object,
    *,
    valid_branch_keys: frozenset[str],
    inherited_next: GateShellNext,
) -> dict[str, GateShellBranchSpec]:
    data = json_object(value, "shell.branches")
    result: dict[str, GateShellBranchSpec] = {}
    for raw_key, raw_branch in data.items():
        key = str(raw_key)
        if key not in valid_branch_keys:
            raise GateError(
                "invalid_shell",
                f"shell.branches.{key}",
                "shell branch key must be a compiled branch or timeout, stopped, or failed",
            )
        result[key] = GateShellBranchSpec.from_mapping(
            raw_branch,
            target=f"shell.branches.{key}",
            inherited_next=inherited_next,
        )
    return result


def _status(value: object, target: str) -> str:
    if not isinstance(value, str):
        raise GateError("invalid_shell", target, f"{target} must be a string")
    try:
        return clamp_shell_status(
            value,
            max_chars=GATE_SHELL_STATUS_MAX_CHARS,
            ellipsis=GATE_SHELL_STATUS_ELLIPSIS,
            noun="gate shell status",
        )
    except ValueError as exc:
        raise GateError("invalid_shell", target, str(exc)) from exc


def _optional_status(value: object, target: str) -> str | None:
    if value is None:
        return None
    return _status(value, target)


def _suffix(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.startswith("--"):
        raise GateError(
            "invalid_shell",
            "shell.suffix",
            "shell.suffix must be a -- prefixed family suffix",
        )
    canonical = canonical_plan_chain_suffix(value)
    if canonical is None:
        raise GateError(
            "invalid_shell",
            "shell.suffix",
            "shell.suffix must be a recognized family suffix",
        )
    return canonical


def _optional_str(value: object, target: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise GateError("invalid_shell", target, f"{target} must be a string")
    return value


def _optional_role(value: object, target: str) -> str | None:
    role = _optional_str(value, target)
    if role is None:
        return None
    if not _ROLE_RE.fullmatch(role):
        raise GateError(
            "invalid_shell",
            target,
            f"{target} must contain only letters, numbers, and underscores",
        )
    return role


def _raw_prompt(value: object, target: str) -> bool:
    if not isinstance(value, bool):
        raise GateError(
            "invalid_shell",
            f"{target}.raw_prompt",
            "raw_prompt must be a boolean",
        )
    return value


def _next_output(value: object, target: str) -> tuple[str, ...]:
    if isinstance(value, str):
        items = (value,)
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        items = tuple(value)
    else:
        raise GateError(
            "invalid_shell",
            target,
            "next.output must be a string or array of strings",
        )
    if not items:
        raise GateError("invalid_shell", target, "next.output must not be empty")
    invalid = sorted(set(items) - GATE_SHELL_NEXT_OUTPUTS)
    if invalid:
        raise GateError(
            "invalid_shell",
            target,
            "next.output must contain only none, results, tail, or file",
        )
    return items


def _default_accent(key: str) -> str:
    from sase.palette_hash import hash_palette_index

    return _DEFAULT_ACCENTS[hash_palette_index(key, len(_DEFAULT_ACCENTS))]


__all__ = [
    "DEFAULT_GATE_SHELL_PENDING_STATUS",
    "DEFAULT_GATE_SHELL_SETTLED_STATUS",
    "GATE_SHELL_DEFAULT_TIMEOUT_SECONDS",
    "SUBSET_BRANCH_GATE_KINDS",
    "GateShellBranchSpec",
    "GateShellNext",
    "GateShellSpec",
    "subset_branches_allowed",
]
