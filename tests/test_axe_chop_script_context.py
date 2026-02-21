"""Tests for sase.axe.chop_script_context."""

import json

from sase.ace.changespec import (
    ChangeSpec,
    CommentEntry,
    CommitEntry,
    HookEntry,
    HookStatusLine,
    MentorEntry,
    MentorStatusLine,
)
from sase.axe.chop_script_context import (
    ChopScriptContext,
    load_changespecs_from_file,
    read_chop_context,
    serialize_changespecs,
    write_chop_context,
)


class TestChopScriptContextRoundTrip:
    """Context write/read round-trip tests."""

    def test_round_trip(self, tmp_path):
        ctx = ChopScriptContext(
            max_runners=3,
            zombie_timeout_seconds=600,
            query="status:Ready",
            lumberjack_name="hooks",
            state_dir="/tmp/axe/lumberjacks/hooks",
            all_changespecs_file="/tmp/all.json",
            filtered_changespecs_file="/tmp/filtered.json",
        )
        path = str(tmp_path / "ctx.json")
        write_chop_context(ctx, path)
        loaded = read_chop_context(path)
        assert loaded == ctx

    def test_creates_parent_dirs(self, tmp_path):
        ctx = ChopScriptContext(
            max_runners=1,
            zombie_timeout_seconds=100,
            query="",
            lumberjack_name="checks",
            state_dir="/tmp/state",
            all_changespecs_file="/tmp/all.json",
            filtered_changespecs_file="/tmp/filtered.json",
        )
        nested = tmp_path / "a" / "b" / "c" / "ctx.json"
        write_chop_context(ctx, str(nested))
        assert nested.exists()

    def test_json_format(self, tmp_path):
        ctx = ChopScriptContext(
            max_runners=5,
            zombie_timeout_seconds=7200,
            query="",
            lumberjack_name="hooks",
            state_dir="/tmp/state",
            all_changespecs_file="/tmp/all.json",
            filtered_changespecs_file="/tmp/filtered.json",
        )
        path = tmp_path / "ctx.json"
        write_chop_context(ctx, str(path))
        raw = json.loads(path.read_text())
        assert raw["max_runners"] == 5
        assert raw["lumberjack_name"] == "hooks"
        assert isinstance(raw, dict)


class TestChangeSpecSerialization:
    """ChangeSpec serialize/load round-trip tests."""

    def _minimal_changespec(self, name="cs1"):
        return ChangeSpec(
            name=name,
            description="A test changespec",
            parent=None,
            cl=None,
            status="WIP",
            test_targets=None,
            kickstart=None,
            file_path="/tmp/test.gp",
            line_number=1,
        )

    def test_minimal_round_trip(self, tmp_path):
        """No nested dataclasses."""
        cs = self._minimal_changespec()
        path = str(tmp_path / "cs.json")
        serialize_changespecs([cs], path)
        loaded = load_changespecs_from_file(path)
        assert len(loaded) == 1
        assert loaded[0] == cs

    def test_full_round_trip(self, tmp_path):
        """All nested types populated."""
        cs = ChangeSpec(
            name="full",
            description="Full changespec",
            parent="parent_cs",
            cl="12345",
            status="Ready",
            test_targets=["//test:foo"],
            kickstart="run_tests",
            file_path="/tmp/full.gp",
            line_number=10,
            bug="b/999",
            commits=[
                CommitEntry(
                    number=1,
                    note="First commit",
                    chat="chat1",
                    diff="diff1",
                    proposal_letter=None,
                    suffix="NEW PROPOSAL",
                    suffix_type="error",
                ),
                CommitEntry(
                    number=1,
                    note="Proposed fix",
                    proposal_letter="a",
                ),
            ],
            hooks=[
                HookEntry(
                    command="!$presubmit",
                    status_lines=[
                        HookStatusLine(
                            commit_entry_num="1",
                            timestamp="260101_120000",
                            status="PASSED",
                            duration="1m23s",
                            suffix=None,
                            suffix_type=None,
                            summary="All checks passed",
                        ),
                        HookStatusLine(
                            commit_entry_num="2",
                            timestamp="260101_120100",
                            status="RUNNING",
                        ),
                    ],
                ),
                HookEntry(command="lint"),
            ],
            comments=[
                CommentEntry(
                    reviewer="critique",
                    file_path="/tmp/comments.json",
                    suffix="ZOMBIE",
                    suffix_type="error",
                ),
            ],
            mentors=[
                MentorEntry(
                    entry_id="1",
                    profiles=["safety", "style"],
                    status_lines=[
                        MentorStatusLine(
                            profile_name="safety",
                            mentor_name="safe_check",
                            status="PASSED",
                            timestamp="260101_120000",
                            duration="0h2m15s",
                            suffix=None,
                            suffix_type="plain",
                        ),
                    ],
                ),
            ],
        )
        path = str(tmp_path / "full.json")
        serialize_changespecs([cs], path)
        loaded = load_changespecs_from_file(path)
        assert len(loaded) == 1
        assert loaded[0] == cs

    def test_multiple_changespecs(self, tmp_path):
        cs1 = self._minimal_changespec("first")
        cs2 = self._minimal_changespec("second")
        path = str(tmp_path / "multi.json")
        serialize_changespecs([cs1, cs2], path)
        loaded = load_changespecs_from_file(path)
        assert len(loaded) == 2
        assert loaded[0].name == "first"
        assert loaded[1].name == "second"

    def test_empty_list(self, tmp_path):
        path = str(tmp_path / "empty.json")
        serialize_changespecs([], path)
        loaded = load_changespecs_from_file(path)
        assert loaded == []

    def test_creates_parent_dirs(self, tmp_path):
        cs = self._minimal_changespec()
        nested = tmp_path / "x" / "y" / "cs.json"
        serialize_changespecs([cs], str(nested))
        assert nested.exists()
