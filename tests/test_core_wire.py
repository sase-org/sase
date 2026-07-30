"""Tests for sase.core wire records and Python -> wire conversion."""

from __future__ import annotations

import json

from sase.ace.changespec.models import (
    ChangeSpec,
    CommentEntry,
    CommitEntry,
    DeltaEntry,
    HookEntry,
    HookStatusLine,
    MentorEntry,
    MentorStatusLine,
    TimestampEntry,
)
from sase.ace.changespec.parser import parse_project_file
from sase.core.wire import (
    CHANGESPEC_WIRE_SCHEMA_VERSION,
    ChangeSpecWire,
    CommitWire,
    ParseErrorWire,
    SourceSpanWire,
    known_field_kwargs,
    to_json_dict,
)
from sase.core.wire_conversion import (
    changespec_to_wire,
    changespec_wire_from_dict,
    comment_entry_to_wire,
    _commit_entry_to_wire,
    _mentor_status_line_to_wire,
    hook_entry_to_wire,
    _hook_status_line_to_wire,
    mentor_entry_to_wire,
)


def _full_changespec() -> ChangeSpec:
    return ChangeSpec(
        name="my_feature",
        description="A short description.",
        parent="parent_feature",
        cl="PR/42",
        status="WIP",
        file_path="/proj/myproj.sase",
        line_number=10,
        project_display_name="widgets",
        bug="BUG-1",
        commits=[
            CommitEntry(
                number=1,
                note="initial",
                chat="chat-1",
                diff="diff-1",
                plan="plan-1",
                proposal_letter=None,
                suffix="ZOMBIE",
                suffix_type="error",
                body=["line1", "", "line2"],
            ),
            CommitEntry(
                number=2,
                note="proposed",
                proposal_letter="a",
            ),
        ],
        hooks=[
            HookEntry(
                command="!sase_lint",
                status_lines=[
                    HookStatusLine(
                        commit_entry_num="1",
                        timestamp="260429_120000",
                        status="PASSED",
                        duration="1m23s",
                        suffix=None,
                        suffix_type=None,
                        summary=None,
                    )
                ],
            )
        ],
        comments=[
            CommentEntry(
                reviewer="critique",
                file_path="~/.sase/comments/c.json",
                suffix="Unresolved Critique Comments",
                suffix_type="error",
            )
        ],
        mentors=[
            MentorEntry(
                entry_id="1",
                profiles=["profileA"],
                status_lines=[
                    MentorStatusLine(
                        profile_name="profileA",
                        mentor_name="mentor1",
                        status="PASSED",
                        timestamp="260429_120000",
                        duration="0h2m15s",
                    )
                ],
                is_draft=False,
            )
        ],
        timestamps=[
            TimestampEntry(
                timestamp="2026-04-29 12:00:00",
                event_type="STATUS",
                detail="WIP -> Draft",
            )
        ],
        deltas=[
            DeltaEntry(path="src/added.py", change_type="A"),
            DeltaEntry(path="src/mod.py", change_type="M"),
            DeltaEntry(path="src/del.py", change_type="D"),
        ],
    )


def test_commit_entry_to_wire_preserves_fields() -> None:
    entry = CommitEntry(number=3, note="n", body=["a", "b"])
    wire = _commit_entry_to_wire(entry)
    assert isinstance(wire, CommitWire)
    assert wire.number == 3
    assert wire.body == ["a", "b"]


def test_commit_entry_with_no_body_yields_empty_list() -> None:
    entry = CommitEntry(number=1, note="x", body=None)
    wire = _commit_entry_to_wire(entry)
    assert wire.body == []


def test_changespec_to_wire_full_round_trip() -> None:
    cs = _full_changespec()
    wire = changespec_to_wire(cs, end_line=42)

    assert isinstance(wire, ChangeSpecWire)
    assert wire.schema_version == CHANGESPEC_WIRE_SCHEMA_VERSION
    assert wire.name == "my_feature"
    assert wire.project_basename == "myproj"
    assert wire.project_display_name == "widgets"
    assert wire.source_span == SourceSpanWire(
        file_path="/proj/myproj.sase", start_line=10, end_line=42
    )
    assert wire.pr_url == "PR/42"
    assert wire.bug == "BUG-1"
    assert wire.refs == []
    assert len(wire.commits) == 2
    assert wire.commits[0].suffix == "ZOMBIE"
    assert wire.commits[0].suffix_type == "error"
    assert wire.commits[0].body == ["line1", "", "line2"]
    assert wire.commits[1].proposal_letter == "a"
    assert wire.hooks[0].status_lines[0].timestamp == "260429_120000"
    assert wire.comments[0].reviewer == "critique"
    assert wire.mentors[0].profiles == ["profileA"]
    assert wire.timestamps[0].event_type == "STATUS"
    assert [d.change_type for d in wire.deltas] == ["A", "M", "D"]


def test_running_mentor_without_timestamp_serializes_as_null(tmp_path) -> None:
    project = tmp_path / "myproj.sase"
    project.write_text(
        """\
NAME: missing_mentor_timestamp
DESCRIPTION:
PARENT:
PR:
STATUS: WIP
MENTORS:
  (1) profileA[1/1]
      | profileA:mentor1 - RUNNING - (@: mentor_mentor1-123-260101_130000)
"""
    )

    cs = parse_project_file(str(project))[0]
    wire = changespec_to_wire(cs)
    payload = to_json_dict(wire)

    assert cs.mentors is not None
    assert cs.mentors[0].status_lines is not None
    status_line = cs.mentors[0].status_lines[0]
    assert status_line.timestamp is None
    assert wire.mentors[0].status_lines[0].timestamp is None
    assert payload["mentors"][0]["status_lines"][0]["timestamp"] is None


def test_changespec_to_wire_default_end_line_equals_start() -> None:
    cs = ChangeSpec(
        name="a",
        description="",
        parent=None,
        cl=None,
        status="WIP",
        file_path="/p/proj.sase",
        line_number=7,
    )
    wire = changespec_to_wire(cs)
    assert wire.source_span.start_line == 7
    assert wire.source_span.end_line == 7


def test_to_json_dict_is_json_serializable() -> None:
    cs = _full_changespec()
    wire = changespec_to_wire(cs, end_line=20)
    payload = to_json_dict(wire)
    # Must round-trip through json.dumps without TypeError:
    text = json.dumps(payload, sort_keys=True)
    reloaded = json.loads(text)
    assert reloaded["name"] == "my_feature"
    assert reloaded["schema_version"] == CHANGESPEC_WIRE_SCHEMA_VERSION
    assert reloaded["source_span"]["start_line"] == 10
    assert reloaded["source_span"]["end_line"] == 20
    assert reloaded["deltas"][0]["change_type"] == "A"


def test_to_json_dict_handles_lists_and_primitives() -> None:
    assert to_json_dict([1, 2, 3]) == [1, 2, 3]
    assert to_json_dict("foo") == "foo"
    assert to_json_dict(None) is None
    assert to_json_dict({"a": 1}) == {"a": 1}


def test_individual_to_wire_helpers() -> None:
    cs = _full_changespec()
    assert _hook_status_line_to_wire(cs.hooks[0].status_lines[0]).status == "PASSED"
    assert hook_entry_to_wire(cs.hooks[0]).command == "!sase_lint"
    assert comment_entry_to_wire(cs.comments[0]).reviewer == "critique"
    assert (
        _mentor_status_line_to_wire(cs.mentors[0].status_lines[0]).profile_name
        == "profileA"
    )
    assert mentor_entry_to_wire(cs.mentors[0]).entry_id == "1"


def test_parse_error_wire_optional_position() -> None:
    err = ParseErrorWire(
        kind="invalid-status",
        message="STATUS field missing",
        file_path="/p/proj.sase",
    )
    payload = to_json_dict(err)
    assert payload["line"] is None
    assert payload["column"] is None
    assert payload["kind"] == "invalid-status"


def test_changespec_wire_from_dict_round_trips_full_record() -> None:
    """Rust emits dicts; ``changespec_wire_from_dict`` rehydrates them.

    Round-trip a fully populated wire record through ``to_json_dict`` and
    back: the result must equal the original dataclass tree.
    """
    cs = _full_changespec()
    wire = changespec_to_wire(cs, end_line=99)
    payload = to_json_dict(wire)

    rehydrated = changespec_wire_from_dict(payload)
    assert rehydrated == wire


def test_changespec_wire_from_dict_rejects_unknown_schema_version() -> None:
    """Unsupported schema versions are explicit errors, not silent drift."""
    payload = {
        "schema_version": CHANGESPEC_WIRE_SCHEMA_VERSION + 1,
        "name": "x",
        "project_basename": "p",
        "file_path": "p.sase",
        "source_span": {"file_path": "p.sase", "start_line": 1, "end_line": 1},
        "status": "WIP",
        "parent": None,
        "pr_url": None,
        "bug": None,
        "description": "",
    }
    try:
        changespec_wire_from_dict(payload)
    except ValueError as exc:
        assert "schema_version" in str(exc)
    else:
        raise AssertionError("expected ValueError on bumped schema_version")


def test_changespec_wire_from_dict_treats_missing_lists_as_empty() -> None:
    """Rust may serialize empty lists implicitly (None); accept either form."""
    payload = {
        "schema_version": CHANGESPEC_WIRE_SCHEMA_VERSION,
        "name": "x",
        "project_basename": "p",
        "file_path": "p.sase",
        "source_span": {"file_path": "p.sase", "start_line": 1, "end_line": 1},
        "status": "WIP",
        "parent": None,
        "pr_url": None,
        "bug": None,
        "description": "",
    }
    wire = changespec_wire_from_dict(payload)
    assert wire.refs == []
    assert wire.commits == []
    assert wire.deltas == []


def test_changespec_wire_from_schema_four_defaults_refs() -> None:
    """Version 4 records predate the REFS section."""
    payload = {
        "schema_version": 4,
        "name": "x",
        "project_basename": "p",
        "file_path": "/tmp/p/p.sase",
        "source_span": {
            "file_path": "/tmp/p/p.sase",
            "start_line": 1,
            "end_line": 1,
        },
        "status": "WIP",
        "parent": None,
        "pr_url": None,
        "bug": None,
        "description": "",
    }
    assert changespec_wire_from_dict(payload).refs == []


def test_changespec_wire_from_older_dict_defaults_project_name_metadata() -> None:
    """Version 3 records predate configured project query metadata."""
    payload = {
        "schema_version": 3,
        "name": "x",
        "project_basename": "p",
        "file_path": "/tmp/p/p.sase",
        "source_span": {
            "file_path": "/tmp/p/p.sase",
            "start_line": 1,
            "end_line": 1,
        },
        "status": "WIP",
        "parent": None,
        "pr_url": None,
        "bug": None,
        "description": "",
    }
    wire = changespec_wire_from_dict(payload)
    assert wire.project_display_name is None


def test_known_field_kwargs_drops_unknown_keys_and_keeps_known() -> None:
    """A newer writer's additive fields must be ignored, never a TypeError."""
    payload = {
        "file_path": "p.sase",
        "start_line": 3,
        "end_line": 9,
        "added_by_newer_writer": "ignored",
    }
    kwargs = known_field_kwargs(SourceSpanWire, payload)
    assert kwargs == {"file_path": "p.sase", "start_line": 3, "end_line": 9}
    span = SourceSpanWire(**kwargs)
    assert span.start_line == 3


def test_empty_changespec_collections_become_empty_lists() -> None:
    cs = ChangeSpec(
        name="empty",
        description="",
        parent=None,
        cl=None,
        status="WIP",
        file_path="/p/proj.sase",
        line_number=1,
    )
    wire = changespec_to_wire(cs)
    assert wire.commits == []
    assert wire.hooks == []
    assert wire.comments == []
    assert wire.mentors == []
    assert wire.timestamps == []
    assert wire.deltas == []
