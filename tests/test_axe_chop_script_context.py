"""Tests for sase.axe.chop_script_context."""

import json

from sase.ace.patch import (
    Patch,
    CommentEntry,
    CommitEntry,
    HookEntry,
    HookStatusLine,
    MentorEntry,
    MentorStatusLine,
)
from sase.axe.chop_script_context import (
    ChopScriptContext,
    load_patches_from_file,
    prepare_chop_run_context,
    read_chop_context,
    serialize_patches,
    write_chop_context,
)


class TestChopScriptContextRoundTrip:
    """Context write/read round-trip tests."""

    def test_round_trip(self, tmp_path):
        ctx = ChopScriptContext(
            max_hook_runners=3,
            max_agent_runners=3,
            zombie_timeout_seconds=600,
            query="status:Ready",
            lumberjack_name="hooks",
            state_dir="/tmp/axe/lumberjacks/hooks",
            all_patches_file="/tmp/all.json",
            filtered_patches_file="/tmp/filtered.json",
        )
        path = str(tmp_path / "ctx.json")
        write_chop_context(ctx, path)
        loaded = read_chop_context(path)
        assert loaded == ctx

    def test_legacy_context_defaults_source_and_dry_run(self, tmp_path):
        path = tmp_path / "legacy.json"
        path.write_text(
            json.dumps(
                {
                    "max_hook_runners": 3,
                    "max_agent_runners": 3,
                    "zombie_timeout_seconds": 600,
                    "query": "",
                    "lumberjack_name": "hooks",
                    "state_dir": "/tmp/axe/lumberjacks/hooks",
                    "all_patches_file": "/tmp/all.json",
                    "filtered_patches_file": "/tmp/filtered.json",
                }
            ),
            encoding="utf-8",
        )

        loaded = read_chop_context(str(path))

        assert loaded.source == "scheduled"
        assert loaded.dry_run is False

    def test_unknown_context_fields_are_ignored(self, tmp_path):
        path = tmp_path / "future.json"
        path.write_text(
            json.dumps(
                {
                    "max_hook_runners": 3,
                    "max_agent_runners": 3,
                    "zombie_timeout_seconds": 600,
                    "query": "",
                    "lumberjack_name": "hooks",
                    "state_dir": "/tmp/axe/lumberjacks/hooks",
                    "all_patches_file": "/tmp/all.json",
                    "filtered_patches_file": "/tmp/filtered.json",
                    "source": "manual",
                    "dry_run": True,
                    "future_field": {"nested": "value"},
                }
            ),
            encoding="utf-8",
        )

        loaded = read_chop_context(str(path))

        assert loaded.source == "manual"
        assert loaded.dry_run is True

    def test_prepare_chop_run_context_adds_run_fields(self, tmp_path):
        base = tmp_path / "base.json"
        destination = tmp_path / "run.json"
        base.write_text(
            json.dumps(
                {
                    "max_hook_runners": 3,
                    "max_agent_runners": 3,
                    "zombie_timeout_seconds": 600,
                    "query": "",
                    "lumberjack_name": "hooks",
                    "state_dir": "/tmp/axe/lumberjacks/hooks",
                    "all_patches_file": "/tmp/all.json",
                    "filtered_patches_file": "/tmp/filtered.json",
                }
            ),
            encoding="utf-8",
        )

        result = prepare_chop_run_context(
            str(base),
            result_file="/tmp/result.json",
            destination=str(destination),
            source="manual",
            dry_run=True,
            target={"repo": "sase"},
            vars={"limit": 1},
        )

        assert result == str(destination)
        loaded = read_chop_context(str(destination))
        assert loaded.result_file == "/tmp/result.json"
        assert loaded.source == "manual"
        assert loaded.dry_run is True
        assert loaded.target == {"repo": "sase"}
        assert loaded.vars == {"limit": 1}


class TestPatchSerialization:
    """Patch serialize/load round-trip tests."""

    def _minimal_patch(self, name="cs1"):
        return Patch(
            name=name,
            description="A test patch",
            parent=None,
            cl=None,
            status="WIP",
            file_path="/tmp/test.sase",
            line_number=1,
        )

    def test_minimal_round_trip(self, tmp_path):
        """No nested dataclasses."""
        cs = self._minimal_patch()
        path = str(tmp_path / "cs.json")
        serialize_patches([cs], path)
        loaded = load_patches_from_file(path)
        assert len(loaded) == 1
        assert loaded[0] == cs

    def test_full_round_trip(self, tmp_path):
        """All nested types populated."""
        cs = Patch(
            name="full",
            description="Full patch",
            parent="parent_cs",
            cl="12345",
            pr_origin="external",
            status="Ready",
            file_path="/tmp/full.sase",
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
        serialize_patches([cs], path)
        loaded = load_patches_from_file(path)
        assert len(loaded) == 1
        assert loaded[0] == cs
