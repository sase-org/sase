"""Reusable Patch fixtures for ace tests."""

from sase.ace.patch import (
    Patch,
    CommentEntry,
    Stitch,
    DeltaEntry,
    HookEntry,
)


def make_patch(
    name: str = "test_feature",
    description: str = "Test description",
    status: str = "Ready",
    cl: str | None = None,
    parent: str | None = None,
    file_path: str = "/tmp/test.sase",
    commits: list[Stitch] | None = None,
    hooks: list[HookEntry] | None = None,
    comments: list[CommentEntry] | None = None,
    deltas: list[DeltaEntry] | None = None,
    pr_origin: str | None = None,
) -> Patch:
    """Create a Patch for testing."""
    return Patch(
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
        pr_origin=pr_origin,
    )


DEFAULT_PATCHES = [
    make_patch(name="feature_a"),
    make_patch(name="feature_b"),
    make_patch(name="feature_c"),
]
make_changespec = make_patch  # legacy compatibility alias
DEFAULT_CHANGESPECS = DEFAULT_PATCHES  # legacy compatibility alias
