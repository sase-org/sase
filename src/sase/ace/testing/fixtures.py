"""Reusable ChangeSpec fixtures for ace tests."""

from sase.ace.changespec import (
    ChangeSpec,
    CommentEntry,
    CommitEntry,
    DeltaEntry,
    HookEntry,
)


def make_changespec(
    name: str = "test_feature",
    description: str = "Test description",
    status: str = "Ready",
    cl: str | None = None,
    parent: str | None = None,
    file_path: str = "/tmp/test.sase",
    commits: list[CommitEntry] | None = None,
    hooks: list[HookEntry] | None = None,
    comments: list[CommentEntry] | None = None,
    deltas: list[DeltaEntry] | None = None,
) -> ChangeSpec:
    """Create a ChangeSpec for testing."""
    return ChangeSpec(
        name=name,
        description=description,
        parent=parent,
        cl=cl,
        status=status,
        file_path=file_path,
        line_number=1,
        commits=commits,
        hooks=hooks,
        comments=comments,
        deltas=deltas,
    )


DEFAULT_CHANGESPECS = [
    make_changespec(name="feature_a"),
    make_changespec(name="feature_b"),
    make_changespec(name="feature_c"),
]
