"""Extra tests for query evaluator — covers _get_searchable_text edge cases."""

from inline_snapshot import snapshot

from sase.ace.changespec import (
    ChangeSpec,
    CommentEntry,
    CommitEntry,
    HookEntry,
    HookStatusLine,
    MentorEntry,
    MentorStatusLine,
)
from sase.ace.query.evaluator import _get_searchable_text, evaluate_query
from sase.ace.query.parser import parse_query


def _cs(
    name: str = "test",
    description: str = "desc",
    status: str = "Ready",
    cl: str | None = None,
    parent: str | None = None,
    kickstart: str | None = None,
    commits: list[CommitEntry] | None = None,
    hooks: list[HookEntry] | None = None,
    comments: list[CommentEntry] | None = None,
    mentors: list[MentorEntry] | None = None,
) -> ChangeSpec:
    return ChangeSpec(
        name=name,
        description=description,
        parent=parent,
        cl=cl,
        status=status,
        test_targets=None,
        kickstart=kickstart,
        file_path="/home/user/.sase/projects/myproject/myproject.gp",
        line_number=1,
        commits=commits,
        hooks=hooks,
        comments=comments,
        mentors=mentors,
    )


class TestGetSearchableTextEdgeCases:
    def test_includes_parent(self) -> None:
        cs = _cs(parent="parent_cl")
        text = _get_searchable_text(cs)
        assert "parent_cl" in text

    def test_includes_cl(self) -> None:
        cs = _cs(cl="CL-12345")
        text = _get_searchable_text(cs)
        assert "CL-12345" in text

    def test_includes_kickstart(self) -> None:
        cs = _cs(kickstart="some_kickstart")
        text = _get_searchable_text(cs)
        assert "some_kickstart" in text

    def test_hook_running_agent_with_suffix(self) -> None:
        cs = _cs(
            hooks=[
                HookEntry(
                    command="my_hook",
                    status_lines=[
                        HookStatusLine(
                            commit_entry_num="1",
                            timestamp="250101",
                            status="RUNNING",
                            suffix="agent-123",
                            suffix_type="running_agent",
                        )
                    ],
                )
            ]
        )
        text = _get_searchable_text(cs)
        assert "- (@: agent-123)" in text

    def test_hook_running_agent_no_suffix(self) -> None:
        cs = _cs(
            hooks=[
                HookEntry(
                    command="my_hook",
                    status_lines=[
                        HookStatusLine(
                            commit_entry_num="1",
                            timestamp="250101",
                            status="RUNNING",
                            suffix_type="running_agent",
                        )
                    ],
                )
            ]
        )
        text = _get_searchable_text(cs)
        assert "- (@)" in text

    def test_hook_running_process(self) -> None:
        cs = _cs(
            hooks=[
                HookEntry(
                    command="my_hook",
                    status_lines=[
                        HookStatusLine(
                            commit_entry_num="1",
                            timestamp="250101",
                            status="RUNNING",
                            suffix="12345",
                            suffix_type="running_process",
                        )
                    ],
                )
            ]
        )
        text = _get_searchable_text(cs)
        assert "- ($: 12345)" in text

    def test_hook_killed_process(self) -> None:
        cs = _cs(
            hooks=[
                HookEntry(
                    command="my_hook",
                    status_lines=[
                        HookStatusLine(
                            commit_entry_num="1",
                            timestamp="250101",
                            status="KILLED",
                            suffix="99999",
                            suffix_type="killed_process",
                        )
                    ],
                )
            ]
        )
        text = _get_searchable_text(cs)
        assert "- (~$: 99999)" in text

    def test_comment_running_agent(self) -> None:
        cs = _cs(
            comments=[
                CommentEntry(
                    reviewer="critique",
                    file_path="/tmp/c.json",
                    suffix="crs-agent",
                    suffix_type="running_agent",
                )
            ]
        )
        text = _get_searchable_text(cs)
        assert "- (@: crs-agent)" in text

    def test_comment_running_agent_no_suffix(self) -> None:
        cs = _cs(
            comments=[
                CommentEntry(
                    reviewer="critique",
                    file_path="/tmp/c.json",
                    suffix_type="running_agent",
                )
            ]
        )
        text = _get_searchable_text(cs)
        assert "- (@)" in text

    def test_comment_running_process(self) -> None:
        cs = _cs(
            comments=[
                CommentEntry(
                    reviewer="critique",
                    file_path="/tmp/c.json",
                    suffix="55555",
                    suffix_type="running_process",
                )
            ]
        )
        text = _get_searchable_text(cs)
        assert "- ($: 55555)" in text

    def test_comment_killed_process(self) -> None:
        cs = _cs(
            comments=[
                CommentEntry(
                    reviewer="critique",
                    file_path="/tmp/c.json",
                    suffix="77777",
                    suffix_type="killed_process",
                )
            ]
        )
        text = _get_searchable_text(cs)
        assert "- (~$: 77777)" in text

    def test_comment_error_suffix(self) -> None:
        cs = _cs(
            comments=[
                CommentEntry(
                    reviewer="critique",
                    file_path="/tmp/c.json",
                    suffix="timeout",
                    suffix_type="error",
                )
            ]
        )
        text = _get_searchable_text(cs)
        assert "(!: timeout)" in text

    def test_comment_plain_suffix(self) -> None:
        cs = _cs(
            comments=[
                CommentEntry(
                    reviewer="critique",
                    file_path="/tmp/c.json",
                    suffix="resolved",
                    suffix_type="plain",
                )
            ]
        )
        text = _get_searchable_text(cs)
        assert "(resolved)" in text

    def test_mentor_running_agent(self) -> None:
        cs = _cs(
            mentors=[
                MentorEntry(
                    entry_id="1",
                    profiles=["default"],
                    status_lines=[
                        MentorStatusLine(
                            profile_name="default",
                            mentor_name="review",
                            status="RUNNING",
                            timestamp="250101",
                            suffix="mentor-abc",
                            suffix_type="running_agent",
                        )
                    ],
                )
            ]
        )
        text = _get_searchable_text(cs)
        assert "- (@: mentor-abc)" in text

    def test_mentor_running_agent_no_suffix(self) -> None:
        cs = _cs(
            mentors=[
                MentorEntry(
                    entry_id="1",
                    profiles=["default"],
                    status_lines=[
                        MentorStatusLine(
                            profile_name="default",
                            mentor_name="review",
                            status="RUNNING",
                            timestamp="250101",
                            suffix_type="running_agent",
                        )
                    ],
                )
            ]
        )
        text = _get_searchable_text(cs)
        assert "- (@)" in text

    def test_mentor_error_suffix(self) -> None:
        cs = _cs(
            mentors=[
                MentorEntry(
                    entry_id="1",
                    profiles=["default"],
                    status_lines=[
                        MentorStatusLine(
                            profile_name="default",
                            mentor_name="review",
                            status="FAILED",
                            timestamp="250101",
                            suffix="crashed",
                            suffix_type="error",
                        )
                    ],
                )
            ]
        )
        text = _get_searchable_text(cs)
        assert "(!: crashed)" in text

    def test_mentor_plain_suffix(self) -> None:
        cs = _cs(
            mentors=[
                MentorEntry(
                    entry_id="1",
                    profiles=["default"],
                    status_lines=[
                        MentorStatusLine(
                            profile_name="default",
                            mentor_name="review",
                            status="PASSED",
                            timestamp="250101",
                            suffix="0h2m15s",
                        )
                    ],
                )
            ]
        )
        text = _get_searchable_text(cs)
        assert "(0h2m15s)" in text

    def test_commit_error_suffix(self) -> None:
        cs = _cs(
            commits=[
                CommitEntry(
                    number=1, note="change", suffix="BROKE", suffix_type="error"
                )
            ]
        )
        text = _get_searchable_text(cs)
        assert "(!: BROKE)" in text

    def test_commit_plain_suffix(self) -> None:
        cs = _cs(
            commits=[
                CommitEntry(
                    number=1, note="change", suffix="NEW PROPOSAL", suffix_type="plain"
                )
            ]
        )
        text = _get_searchable_text(cs)
        assert "(NEW PROPOSAL)" in text


class TestEvaluateQueryIntegration:
    def test_running_agent_query(self) -> None:
        cs = _cs(
            hooks=[
                HookEntry(
                    command="hook",
                    status_lines=[
                        HookStatusLine(
                            commit_entry_num="1",
                            timestamp="250101",
                            status="RUNNING",
                            suffix="agent",
                            suffix_type="running_agent",
                        )
                    ],
                )
            ]
        )
        query = parse_query("@@@")
        assert evaluate_query(query, cs) is True

    def test_running_process_query(self) -> None:
        cs = _cs(
            hooks=[
                HookEntry(
                    command="hook",
                    status_lines=[
                        HookStatusLine(
                            commit_entry_num="1",
                            timestamp="250101",
                            status="RUNNING",
                            suffix="12345",
                            suffix_type="running_process",
                        )
                    ],
                )
            ]
        )
        query = parse_query("$$$")
        assert evaluate_query(query, cs) is True
