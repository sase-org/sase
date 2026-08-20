"""SASE's builtin declarative task-type specs.

The five host types — ``bug``, ``ci``, ``feature``, ``flake``, and ``memory`` —
register through the same hookspec plugins use. Builtin slugs are reserved
against plugin definitions; a project-config ``use: builtin@<slug>`` entry may
still override one.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._hookspec import hookimpl

_TASK_TYPE_SPEC_SCHEMA_VERSION = 1

_DATA_AND_TEMPLATE = ("data", "template")
_TEMPLATE_ONLY = ("template",)
_DATA_ONLY = ("data",)


def _field(
    name: str,
    *,
    field_type: str = "string",
    required: bool = False,
    role: tuple[str, ...] = _DATA_AND_TEMPLATE,
    label: str | None = None,
    help: str | None = None,
    pattern: str | None = None,
) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "name": name,
        "type": field_type,
        "required": required,
        "role": list(role),
    }
    if label is not None:
        spec["label"] = label
    if help is not None:
        spec["help"] = help
    if pattern is not None:
        spec["pattern"] = pattern
    return spec


def _bug_spec() -> dict[str, Any]:
    """A defect found while doing unrelated work, not an external tracker bug."""

    return {
        "schema_version": _TASK_TYPE_SPEC_SCHEMA_VERSION,
        "task_type": "bug",
        "label": "Bug",
        "summary": (
            "A defect an agent found while doing unrelated work, not an "
            "external tracker bug."
        ),
        "when_to_use": (
            "File one when you found a defect while doing unrelated work and "
            "it is not an external tracker issue. Record where it lives, how "
            "to reproduce it, and who it hurts. Do not use this for a flake, "
            "a confirmed CI failure, or a GitHub-mirrored bug."
        ),
        "glyph": "⨯",
        "accent_color": "#FF5F5F",
        "fields": [
            _field(
                "location",
                required=True,
                label="Location",
                help="File, symbol, or other locator for the defect",
            ),
            _field(
                "repro",
                required=True,
                role=_TEMPLATE_ONLY,
                label="Repro",
                help="Steps or command that reproduce the defect",
            ),
            _field(
                "impact",
                role=_TEMPLATE_ONLY,
                label="Impact",
                help="Who or what the defect breaks, and how badly",
            ),
        ],
        "body_template": (
            "## Bug\n"
            "\n"
            "- **Location:** `{{ location }}`\n"
            "\n"
            "{{ repro }}\n"
            "\n"
            "{{ impact }}\n"
        ),
    }


def _ci_spec() -> dict[str, Any]:
    """A confirmed true failure; the complement of ``flake``."""

    return {
        "schema_version": _TASK_TYPE_SPEC_SCHEMA_VERSION,
        "task_type": "ci",
        "label": "CI failure",
        "summary": "A confirmed true test or lint failure, not a flake.",
        "when_to_use": (
            "File one when a test or lint failed and you confirmed it is a "
            "true failure, not a flake. Record the pytest node ID, the "
            "failing SHA if known, and why this is not intermittent. Use "
            "flake instead when a rerun on the same tree passed."
        ),
        "glyph": "⚙",
        "accent_color": "#D7D700",
        "fields": [
            _field(
                "node_id",
                required=True,
                label="Test node ID",
                help="The pytest node ID, e.g. tests/foo.py::test_bar",
            ),
            _field(
                "sha",
                role=_DATA_ONLY,
                label="SHA",
                help="Commit SHA where the failure was observed",
            ),
            _field(
                "why_not_flake",
                required=True,
                role=_TEMPLATE_ONLY,
                label="Why not a flake",
                help="Why this is a confirmed true failure rather than a flake",
            ),
        ],
        "body_template": (
            "## CI failure\n\n- **Node:** `{{ node_id }}`\n\n{{ why_not_flake }}\n"
        ),
        "triage": {"min_plus_ones": 0},
    }


def _feature_spec() -> dict[str, Any]:
    """An out-of-scope idea; ``why_out_of_scope`` keeps it off the wish list."""

    return {
        "schema_version": _TASK_TYPE_SPEC_SCHEMA_VERSION,
        "task_type": "feature",
        "label": "Feature",
        "summary": "An out-of-scope product idea that should not become a wish list.",
        "when_to_use": (
            "File one when you discovered a product or capability idea that "
            "is outside the current task or epic. State the proposal and why "
            "it is out of scope for the work you were doing. Do not file one "
            "for in-scope follow-up that belongs on the current epic."
        ),
        "create_refusal": (
            "Agents never create this type with `sase bead create` or "
            "`/sase_new_task` when it is not agent-creatable. That is the "
            "machine-global override outside the SASE project. File a feature "
            "bead only in SASE, or use an in-scope type here."
        ),
        "glyph": "✦",
        "accent_color": "#5FD75F",
        "fields": [
            _field(
                "proposal",
                required=True,
                role=_TEMPLATE_ONLY,
                label="Proposal",
                help="What should exist that is outside the current work",
            ),
            _field(
                "why_out_of_scope",
                required=True,
                role=_TEMPLATE_ONLY,
                label="Why out of scope",
                help="Why this does not belong on the current task or epic",
            ),
        ],
        "body_template": (
            "## Feature proposal\n\n{{ proposal }}\n\n{{ why_out_of_scope }}\n"
        ),
    }


def _flake_spec() -> dict[str, Any]:
    """An intermittent failure that must be corroborated."""

    return {
        "schema_version": _TASK_TYPE_SPEC_SCHEMA_VERSION,
        "task_type": "flake",
        "label": "Flaky test",
        "summary": "A test that fails and then passes on an unchanged tree.",
        "when_to_use": (
            "File one when a test or lint failed, a rerun on the same tree "
            "passed, and you did not cause the failure. Record the fail rate "
            "and whether it reproduces serially. Use ci instead when the "
            "failure is confirmed and reproducible."
        ),
        "glyph": "≈",
        "accent_color": "#00D7D7",
        "fields": [
            _field(
                "node_id",
                required=True,
                label="Test node ID",
                help="The pytest node ID, e.g. tests/foo.py::test_bar",
                pattern=r"\S+::\S+",
            ),
            _field(
                "repro_cmd",
                label="Repro command",
                help="Command that reproduced the intermittent failure",
            ),
            _field(
                "evidence",
                required=True,
                role=_TEMPLATE_ONLY,
                label="Evidence",
                help="Fail/pass observations, fail rate, and serial vs parallel",
            ),
        ],
        "body_template": (
            "## Flake report\n"
            "\n"
            "- **Test:** `{{ node_id }}`\n"
            "- **Repro:** `{{ repro_cmd }}`\n"
            "\n"
            "{{ evidence }}\n"
        ),
        "triage": {"min_plus_ones": 3},
    }


def _memory_spec() -> dict[str, Any]:
    """A stale memory note or skill; closing still needs explicit permission."""

    return {
        "schema_version": _TASK_TYPE_SPEC_SCHEMA_VERSION,
        "task_type": "memory",
        "label": "Memory",
        "summary": "A sase memory note or skill that is out of date.",
        "when_to_use": (
            "File one when a sase memory file or skill contains out-of-date "
            "information that should be updated. Closing still requires "
            "explicit user permission plus `sase memory init`. Record the "
            "memory path and the proposed change."
        ),
        "glyph": "▤",
        "accent_color": "#8787FF",
        "fields": [
            _field(
                "path",
                required=True,
                label="Path",
                help="Memory note path relative to memory/, e.g. sase_beads.md",
            ),
            _field(
                "proposed_change",
                required=True,
                role=_TEMPLATE_ONLY,
                label="Proposed change",
                help="The correction the memory note should receive",
            ),
        ],
        "body_template": (
            "## Memory update\n\n- **Path:** `{{ path }}`\n\n{{ proposed_change }}\n"
        ),
    }


def _builtin_task_type_specs() -> tuple[dict[str, Any], ...]:
    """Return the five builtin task-type specs in slug order."""

    return (
        _bug_spec(),
        _ci_spec(),
        _feature_spec(),
        _flake_spec(),
        _memory_spec(),
    )


class BuiltinTaskTypes:
    """Builtin task types registered through the task-type host path."""

    @hookimpl
    def task_type_specs(self) -> tuple[Mapping[str, Any], ...]:
        return _builtin_task_type_specs()


__all__ = [
    "BuiltinTaskTypes",
]
