"""Canonical Patch wire compatibility tests."""

from __future__ import annotations

import types

import pytest

from sase.ace.patch import Patch, Stitch
from sase.ace.patch.models import HookEntry, HookStatusLine, MentorEntry
from sase.core import parser_facade
from sase.core.rust import RUST_EXTENSION_MODULE_NAME
from sase.core.wire import (
    PATCH_WIRE_SCHEMA_VERSION,
    ChangeSpecWire,
    PatchWire,
    to_json_dict,
)
from sase.core.wire_conversion import (
    changespec_wire_from_dict,
    patch_to_wire,
    patch_wire_from_dict,
)
from tests._rust_extension_module_helpers import patch_rust_extension


def _base_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "schema_version": PATCH_WIRE_SCHEMA_VERSION,
        "name": "demo",
        "project_basename": "project",
        "project_display_name": None,
        "file_path": "project.sase",
        "source_span": {
            "file_path": "project.sase",
            "start_line": 1,
            "end_line": 8,
        },
        "status": "WIP",
        "parent": None,
        "pr_url": None,
        "bug": None,
        "description": "Demo",
        "refs": [],
        "stitches": [{"number": 1, "note": "Initial"}],
        "hooks": [
            {
                "command": "just test",
                "status_lines": [
                    {
                        "stitch_id": "1",
                        "timestamp": "260808_120000",
                        "status": "PASSED",
                    }
                ],
            }
        ],
        "comments": [],
        "mentors": [{"stitch_id": "1", "profiles": ["default"]}],
        "timestamps": [],
        "deltas": [],
    }
    record.update(overrides)
    return record


def test_patch_to_wire_uses_canonical_stitches_shape() -> None:
    patch = Patch(
        name="demo",
        description="Demo",
        parent=None,
        status="WIP",
        file_path="project.sase",
        line_number=1,
        stitches=[Stitch(number=1, note="Initial")],
        hooks=[
            HookEntry(
                command="just test",
                status_lines=[
                    HookStatusLine(
                        stitch_id="1",
                        timestamp="260808_120000",
                        status="PASSED",
                    )
                ],
            )
        ],
        mentors=[MentorEntry(stitch_id="1", profiles=["default"])],
    )

    wire = patch_to_wire(patch)
    payload = to_json_dict(wire)

    assert isinstance(wire, PatchWire)
    assert list(payload).index("stitches") < list(payload).index("hooks")
    assert "commits" not in payload
    assert payload["stitches"] == [
        {
            "number": 1,
            "note": "Initial",
            "chat": None,
            "diff": None,
            "plan": None,
            "proposal_letter": None,
            "suffix": None,
            "suffix_type": None,
            "body": [],
        }
    ]
    assert payload["hooks"][0]["status_lines"][0]["stitch_id"] == "1"
    assert "commit_entry_num" not in payload["hooks"][0]["status_lines"][0]
    assert payload["mentors"][0]["stitch_id"] == "1"
    assert "entry_id" not in payload["mentors"][0]


def test_patch_wire_from_dict_accepts_legacy_spellings() -> None:
    record = _base_record(
        commits=[{"number": 2, "note": "Legacy"}],
        hooks=[
            {
                "command": "just test",
                "status_lines": [
                    {
                        "commit_entry_num": "2",
                        "timestamp": "260808_120000",
                        "status": "PASSED",
                    }
                ],
            }
        ],
        mentors=[{"entry_id": "2", "profiles": ["default"]}],
    )
    record.pop("stitches")

    wire = patch_wire_from_dict(record)

    assert wire.stitches[0].number == 2
    assert wire.hooks[0].status_lines[0].stitch_id == "2"
    assert wire.mentors[0].stitch_id == "2"


def test_patch_wire_from_dict_rejects_conflicting_history_aliases() -> None:
    record = _base_record(commits=[{"number": 2, "note": "Legacy"}])

    with pytest.raises(ValueError, match="stitches.*commits|commits.*stitches"):
        patch_wire_from_dict(record)


def test_patch_wire_from_dict_rejects_conflicting_stitch_id_aliases() -> None:
    record = _base_record(
        hooks=[
            {
                "command": "just test",
                "status_lines": [
                    {
                        "stitch_id": "1",
                        "commit_entry_num": "2",
                        "timestamp": "260808_120000",
                        "status": "PASSED",
                    }
                ],
            }
        ],
    )

    with pytest.raises(ValueError, match="stitch_id.*commit_entry_num"):
        patch_wire_from_dict(record)


def test_changespec_wire_from_dict_accepts_canonical_spellings() -> None:
    wire = changespec_wire_from_dict(_base_record())

    assert isinstance(wire, ChangeSpecWire)
    assert wire.commits[0].number == 1
    assert wire.hooks[0].status_lines[0].commit_entry_num == "1"
    assert wire.mentors[0].entry_id == "1"


def test_parse_patch_project_bytes_uses_canonical_rust_binding(
    monkeypatch,
) -> None:
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    calls: list[tuple[str, bytes]] = []

    def parse_patch_project_bytes(path: str, data: bytes) -> list[dict[str, object]]:
        calls.append((path, data))
        return [_base_record(file_path=path)]

    fake.parse_patch_project_bytes = parse_patch_project_bytes  # type: ignore[attr-defined]
    patch_rust_extension(monkeypatch, fake)

    wires = parser_facade.parse_patch_project_bytes("project.sase", b"data")

    assert calls == [("project.sase", b"data")]
    assert isinstance(wires[0], PatchWire)
    assert wires[0].stitches[0].note == "Initial"
