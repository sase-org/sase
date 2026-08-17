"""The request shape and option command of the BeadStaleCleanup gate.

Everything here defines what a BeadStaleCleanup gate *is*: its constants, the
one request spec the adapter accepts, the option command wrapper, and the
result schema the close option must emit. Gate validation rebuilds these from
the persisted payload and compares, so each helper must stay a pure function
of its arguments.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from sase.bead._stale_cleanup_gate_preview import (
    bead_stale_cleanup_presentation_note,
    render_bead_stale_cleanup_preview,
    stale_cleanup_age_days,
    stale_cleanup_created_date,
    stale_cleanup_project_label,
)
from sase.bead._task_gate_preview import bounded_gate_title
from sase.notification_gates.entrypoints import gate_command_entrypoint

BeadStaleCleanupAction = Literal["close"]

BEAD_STALE_CLEANUP_KIND = "bead_stale_cleanup"
BEAD_STALE_CLEANUP_CONTINUATION_MODE = "bead_stale_cleanup"
BEAD_STALE_CLEANUP_QUERY = "close"
BEAD_STALE_CLEANUP_CLOSE_OPTION_ID: BeadStaleCleanupAction = "close"
BEAD_STALE_CLEANUP_OPTION_IDS: tuple[BeadStaleCleanupAction, ...] = (
    BEAD_STALE_CLEANUP_CLOSE_OPTION_ID,
)
BEAD_STALE_CLEANUP_PRIMARY_BRANCH = (BEAD_STALE_CLEANUP_CLOSE_OPTION_ID,)
BEAD_STALE_CLEANUP_PREVIEW_PATH = "stale.md"
BEAD_STALE_CLEANUP_COMMAND_PATHS: dict[BeadStaleCleanupAction, str] = {
    BEAD_STALE_CLEANUP_CLOSE_OPTION_ID: "commands/close",
}
BEAD_STALE_CLEANUP_MAX_BEADS = 50
BEAD_STALE_CLEANUP_CLOSE_REASON = "Stale task bead swept from triage."
_CLOSE_CHOICE = "close"
_KEEP_CHOICE = "keep"
_SELECT_ONE_MESSAGE = "select at least one bead to close, or dismiss this gate"


def build_bead_stale_cleanup_gate_spec(
    *,
    request_id: str,
    beads: Sequence[Any],
    omitted_count: int = 0,
    min_plus_ones: int,
    stale_after_days: int,
    stale_cleanup_min_beads: int,
    stale_as_of: str,
    producer: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the only request shape accepted by the BeadStaleCleanup adapter."""
    roster = [_bead_payload(bead) for bead in beads]
    payload = {
        "beads": roster,
        "omitted_count": omitted_count,
        "min_plus_ones": min_plus_ones,
        "stale_after_days": stale_after_days,
        "stale_cleanup_min_beads": stale_cleanup_min_beads,
        "stale_as_of": stale_as_of,
    }
    payload_view = _PayloadView(
        beads=roster,
        omitted_count=omitted_count,
        min_plus_ones=min_plus_ones,
        stale_after_days=stale_after_days,
        stale_cleanup_min_beads=stale_cleanup_min_beads,
        stale_as_of=stale_as_of,
    )
    return {
        "schema_version": 3,
        "kind": BEAD_STALE_CLEANUP_KIND,
        "request_id": request_id,
        "producer": dict(producer or {}),
        "continuation_mode": BEAD_STALE_CLEANUP_CONTINUATION_MODE,
        "payload": payload,
        "presentation": {
            "sender": "bead",
            "icon": "🧹",
            "title": "Stale Task Cleanup",
            "notes": [bead_stale_cleanup_presentation_note(payload_view)],
            "tags": ["bead", "task", "stale"],
            "panel": "beads",
            "panel_icon": "◈",
            "files": [BEAD_STALE_CLEANUP_PREVIEW_PATH],
            "preview": BEAD_STALE_CLEANUP_PREVIEW_PATH,
        },
        "query": BEAD_STALE_CLEANUP_QUERY,
        "primary_branch": list(BEAD_STALE_CLEANUP_PRIMARY_BRANCH),
        "options": [bead_stale_cleanup_option_spec(payload_view)],
        "resources": [
            {
                "path": BEAD_STALE_CLEANUP_COMMAND_PATHS[
                    BEAD_STALE_CLEANUP_CLOSE_OPTION_ID
                ],
                "role": "command",
                "content": bead_stale_cleanup_gate_command_script(len(roster)),
            },
            {
                "path": BEAD_STALE_CLEANUP_PREVIEW_PATH,
                "role": "preview",
                "content": render_bead_stale_cleanup_preview(payload_view),
            },
        ],
        "auto": False,
    }


def bead_stale_cleanup_option_spec(payload: Any) -> dict[str, Any]:
    """Return the only spec the Close selected option is accepted with.

    Shared with kind validation, which rebuilds the option from this helper
    rather than restating its shape, so the per-bead select/unselect inputs
    cannot drift between what the gate is created with and what is accepted.
    """
    return {
        "id": BEAD_STALE_CLEANUP_CLOSE_OPTION_ID,
        "label": "Close selected",
        "icon": "🧹",
        "command": {
            "argv": [
                BEAD_STALE_CLEANUP_COMMAND_PATHS[BEAD_STALE_CLEANUP_CLOSE_OPTION_ID]
            ]
        },
        "result_schema": _bead_stale_cleanup_result_schema(),
        "feedback": "optional",
        "inputs": bead_stale_cleanup_selection_inputs(
            payload.beads, stale_as_of=payload.stale_as_of
        ),
    }


def bead_stale_cleanup_selection_inputs(
    beads: Sequence[Any], *, stale_as_of: str
) -> list[dict[str, Any]]:
    """Return one close/keep declaration per offered bead, in payload order."""
    return [
        _selection_input(index, bead, stale_as_of=stale_as_of)
        for index, bead in enumerate(beads, start=1)
    ]


def _selection_input(index: int, bead: Any, *, stale_as_of: str) -> dict[str, Any]:
    bead_id = str(_bead_attr(bead, "bead_id"))
    title = str(_bead_attr(bead, "title"))
    project = str(_bead_attr(bead, "project"))
    plus_one_count = _bead_attr(bead, "plus_one_count")
    created_at = str(_bead_attr(bead, "created_at"))
    age = stale_cleanup_age_days(created_at, stale_as_of=stale_as_of)
    created_date = stale_cleanup_created_date(created_at)
    return {
        "id": f"bead_{index}",
        "label": bounded_gate_title(bead_id, title),
        "type": "enum",
        "required": False,
        "default": _CLOSE_CHOICE,
        "choices": [
            {"value": _CLOSE_CHOICE, "label": "Close"},
            {"value": _KEEP_CHOICE, "label": "Keep"},
        ],
        "help": (
            f"{stale_cleanup_project_label(project)} · +{plus_one_count} · "
            f"created {created_date} ({age} days ago)"
        ),
    }


def _bead_stale_cleanup_result_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["action", "close_bead_indexes"],
        "properties": {
            "action": {"const": BEAD_STALE_CLEANUP_CLOSE_OPTION_ID},
            "close_bead_indexes": {
                "type": "array",
                "items": {"type": "integer", "minimum": 1},
                "minItems": 1,
                "uniqueItems": True,
            },
        },
        "additionalProperties": False,
    }


def bead_stale_cleanup_gate_command_script(bead_count: int) -> str:
    """Return the only command wrapper accepted by the BeadStaleCleanup adapter.

    The wrapper imports from :mod:`sase.bead.stale_cleanup_gate` because the
    script text is persisted into every gate bundle and revalidated byte for
    byte; the facade keeps that path stable no matter where the entrypoint
    lives. *bead_count* is baked in so the command is bounded by the roster
    it was built for.
    """
    return (
        f"#!{sys.executable}\n"
        "from sase.bead.stale_cleanup_gate import "
        "execute_bead_stale_cleanup_gate_command\n"
        f"raise SystemExit(execute_bead_stale_cleanup_gate_command({bead_count}))\n"
    )


@gate_command_entrypoint
def execute_bead_stale_cleanup_gate_command(bead_count: int) -> int:
    """Validate command input and emit one typed side-effect-free result."""
    try:
        raw_input = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"invalid command input: {exc}", file=sys.stderr)
        return 2
    if not isinstance(raw_input, dict):
        print("stale cleanup command input must be an object", file=sys.stderr)
        return 2
    allowed = {f"bead_{index}" for index in range(1, bead_count + 1)}
    unknown = [key for key in raw_input if key not in allowed and key != "feedback"]
    if unknown:
        print(f"unknown field id: {unknown[0]}", file=sys.stderr)
        return 2
    indexes: list[int] = []
    for index in range(1, bead_count + 1):
        field_id = f"bead_{index}"
        value = raw_input.get(field_id, _CLOSE_CHOICE)
        if value not in {_CLOSE_CHOICE, _KEEP_CHOICE}:
            print(
                f"{field_id} must be {_CLOSE_CHOICE} or {_KEEP_CHOICE}",
                file=sys.stderr,
            )
            return 2
        if value == _CLOSE_CHOICE:
            indexes.append(index)
    if not indexes:
        print(_SELECT_ONE_MESSAGE, file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "action": BEAD_STALE_CLEANUP_CLOSE_OPTION_ID,
                "close_bead_indexes": indexes,
            },
            sort_keys=True,
        )
    )
    return 0


def _bead_payload(bead: Any) -> dict[str, Any]:
    return {
        "project": _bead_attr(bead, "project"),
        "bead_id": _bead_attr(bead, "bead_id"),
        "title": _bead_attr(bead, "title"),
        "created_at": _bead_attr(bead, "created_at"),
        "plus_one_count": _bead_attr(bead, "plus_one_count"),
        "size": _bead_attr(bead, "size"),
    }


def _bead_attr(bead: Any, name: str) -> Any:
    if isinstance(bead, Mapping):
        return bead[name] if name != "size" else bead.get("size")
    return getattr(bead, name)


class _PayloadView:
    """Duck-typed payload used while building a spec from caller arguments."""

    __slots__ = (
        "beads",
        "min_plus_ones",
        "omitted_count",
        "stale_after_days",
        "stale_as_of",
        "stale_cleanup_min_beads",
    )

    def __init__(
        self,
        *,
        beads: list[dict[str, Any]],
        omitted_count: int,
        min_plus_ones: int,
        stale_after_days: int,
        stale_cleanup_min_beads: int,
        stale_as_of: str,
    ) -> None:
        self.beads = beads
        self.omitted_count = omitted_count
        self.min_plus_ones = min_plus_ones
        self.stale_after_days = stale_after_days
        self.stale_cleanup_min_beads = stale_cleanup_min_beads
        self.stale_as_of = stale_as_of
