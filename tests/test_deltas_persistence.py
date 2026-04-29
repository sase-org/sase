"""Tests for DELTAS atomic update helper."""

import os
import tempfile
import threading

from sase.ace.changespec import DeltaEntry
from sase.ace.deltas import (
    CHANGESPEC_SECTION_ORDER,
    apply_deltas_update,
    update_changespec_deltas_field,
)


def _write_tmp(contents: str) -> str:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".gp", delete=False, encoding="utf-8"
    ) as f:
        f.write(contents)
        f.flush()
        return f.name


def test_section_order_constant_places_deltas_between_commits_and_hooks() -> None:
    """DELTAS sits immediately after COMMITS and immediately before HOOKS."""
    idx_commits = CHANGESPEC_SECTION_ORDER.index("COMMITS:")
    idx_deltas = CHANGESPEC_SECTION_ORDER.index("DELTAS:")
    idx_hooks = CHANGESPEC_SECTION_ORDER.index("HOOKS:")
    assert idx_deltas == idx_commits + 1
    assert idx_hooks == idx_deltas + 1


def test_insert_into_changespec_with_no_prior_deltas_section() -> None:
    """Insert DELTAS in canonical position when COMMITS and HOOKS exist."""
    initial = (
        "NAME: my_cl\n"
        "DESCRIPTION:\n"
        "  Test\n"
        "STATUS: Ready\n"
        "COMMITS:\n"
        "  (1) initial\n"
        "HOOKS:\n"
        "  some_command\n"
    )
    path = _write_tmp(initial)
    try:
        deltas = [
            DeltaEntry(path="src/a.py", change_type="A"),
            DeltaEntry(path="src/b.py", change_type="M"),
        ]
        assert update_changespec_deltas_field(path, "my_cl", deltas) is True
        with open(path, encoding="utf-8") as f:
            result = f.read()

        # DELTAS section is present, between COMMITS and HOOKS
        commits_idx = result.index("COMMITS:")
        deltas_idx = result.index("DELTAS:")
        hooks_idx = result.index("HOOKS:")
        assert commits_idx < deltas_idx < hooks_idx

        # Body content
        assert "  + src/a.py\n" in result
        assert "  ~ src/b.py\n" in result
        # Original COMMITS / HOOKS content preserved
        assert "  (1) initial\n" in result
        assert "  some_command\n" in result
    finally:
        os.unlink(path)


def test_insert_when_hooks_absent_uses_next_post_deltas_section() -> None:
    """No HOOKS — insert before the next post-DELTAS section (e.g. COMMENTS)."""
    initial = (
        "NAME: my_cl\n"
        "DESCRIPTION:\n"
        "  Test\n"
        "STATUS: Ready\n"
        "COMMITS:\n"
        "  (1) initial\n"
        "COMMENTS:\n"
        "  [reviewer] some/file.py\n"
    )
    path = _write_tmp(initial)
    try:
        deltas = [DeltaEntry(path="src/a.py", change_type="A")]
        assert update_changespec_deltas_field(path, "my_cl", deltas) is True
        with open(path, encoding="utf-8") as f:
            result = f.read()
        deltas_idx = result.index("DELTAS:")
        comments_idx = result.index("COMMENTS:")
        assert deltas_idx < comments_idx
        assert "  + src/a.py\n" in result
    finally:
        os.unlink(path)


def test_replace_existing_deltas_section() -> None:
    """An existing DELTAS section is replaced with the new entries."""
    initial = (
        "NAME: my_cl\n"
        "DESCRIPTION:\n"
        "  Test\n"
        "STATUS: Ready\n"
        "COMMITS:\n"
        "  (1) initial\n"
        "DELTAS:\n"
        "  + old/path.py\n"
        "  ~ stale.py\n"
        "HOOKS:\n"
        "  some_command\n"
    )
    path = _write_tmp(initial)
    try:
        new_deltas = [
            DeltaEntry(path="new/file.py", change_type="A"),
            DeltaEntry(path="other.py", change_type="D"),
        ]
        assert update_changespec_deltas_field(path, "my_cl", new_deltas) is True
        with open(path, encoding="utf-8") as f:
            result = f.read()

        # Old entries gone, new entries present, single DELTAS header
        assert "old/path.py" not in result
        assert "stale.py" not in result
        assert "  + new/file.py\n" in result
        assert "  - other.py\n" in result
        assert result.count("DELTAS:") == 1

        # Surrounding sections preserved
        assert "  (1) initial\n" in result
        assert "  some_command\n" in result
    finally:
        os.unlink(path)


def test_remove_section_when_given_empty_list() -> None:
    """Empty deltas list removes the existing DELTAS section."""
    initial = (
        "NAME: my_cl\n"
        "DESCRIPTION:\n"
        "  Test\n"
        "STATUS: Ready\n"
        "COMMITS:\n"
        "  (1) initial\n"
        "DELTAS:\n"
        "  + a.py\n"
        "  ~ b.py\n"
        "HOOKS:\n"
        "  some_command\n"
    )
    path = _write_tmp(initial)
    try:
        assert update_changespec_deltas_field(path, "my_cl", []) is True
        with open(path, encoding="utf-8") as f:
            result = f.read()

        assert "DELTAS:" not in result
        assert "  + a.py" not in result
        assert "  ~ b.py" not in result
        # Other sections still intact
        assert "COMMITS:\n" in result
        assert "HOOKS:\n" in result
        assert "  (1) initial\n" in result
        assert "  some_command\n" in result
    finally:
        os.unlink(path)


def test_remove_when_no_existing_section_is_noop() -> None:
    """Empty deltas list on a CS without DELTAS leaves the file unchanged."""
    initial = (
        "NAME: my_cl\n"
        "DESCRIPTION:\n"
        "  Test\n"
        "STATUS: Ready\n"
        "COMMITS:\n"
        "  (1) initial\n"
        "HOOKS:\n"
        "  some_command\n"
    )
    path = _write_tmp(initial)
    try:
        assert update_changespec_deltas_field(path, "my_cl", []) is True
        with open(path, encoding="utf-8") as f:
            result = f.read()
        assert result == initial
    finally:
        os.unlink(path)


def test_only_target_changespec_is_modified() -> None:
    """Other ChangeSpecs in the same file are left untouched."""
    initial = (
        "NAME: cl_one\n"
        "DESCRIPTION:\n"
        "  First\n"
        "STATUS: Ready\n"
        "COMMITS:\n"
        "  (1) one\n"
        "DELTAS:\n"
        "  + one/file.py\n"
        "HOOKS:\n"
        "  cmd_one\n"
        "\n"
        "\n"
        "NAME: cl_two\n"
        "DESCRIPTION:\n"
        "  Second\n"
        "STATUS: Ready\n"
        "COMMITS:\n"
        "  (1) two\n"
        "HOOKS:\n"
        "  cmd_two\n"
    )
    path = _write_tmp(initial)
    try:
        deltas = [DeltaEntry(path="two/added.py", change_type="A")]
        assert update_changespec_deltas_field(path, "cl_two", deltas) is True
        with open(path, encoding="utf-8") as f:
            result = f.read()

        # cl_one's DELTAS untouched
        assert "  + one/file.py\n" in result
        # cl_two now has the new DELTAS, between its COMMITS and HOOKS
        assert "  + two/added.py\n" in result
        # cl_two's DELTAS appears after cl_two's NAME
        cl_two_idx = result.index("NAME: cl_two")
        new_deltas_idx = result.index("two/added.py")
        assert new_deltas_idx > cl_two_idx
    finally:
        os.unlink(path)


def test_insert_at_end_of_changespec_when_no_post_sections() -> None:
    """No HOOKS/COMMENTS/etc. after COMMITS — insert at end of ChangeSpec."""
    initial = (
        "NAME: my_cl\nDESCRIPTION:\n  Test\nSTATUS: Ready\nCOMMITS:\n  (1) initial\n"
    )
    path = _write_tmp(initial)
    try:
        deltas = [DeltaEntry(path="src/a.py", change_type="A")]
        assert update_changespec_deltas_field(path, "my_cl", deltas) is True
        with open(path, encoding="utf-8") as f:
            result = f.read()
        assert "DELTAS:\n" in result
        assert "  + src/a.py\n" in result
        # DELTAS should appear AFTER COMMITS content
        assert result.index("(1) initial") < result.index("DELTAS:")
    finally:
        os.unlink(path)


def test_apply_deltas_update_pure_function() -> None:
    """apply_deltas_update returns the modified line list without I/O."""
    lines = [
        "NAME: my_cl\n",
        "DESCRIPTION:\n",
        "  Test\n",
        "STATUS: Ready\n",
        "COMMITS:\n",
        "  (1) initial\n",
        "HOOKS:\n",
        "  cmd\n",
    ]
    result = apply_deltas_update(
        lines, "my_cl", [DeltaEntry(path="x.py", change_type="A")]
    )
    text = "".join(result)
    assert "DELTAS:\n" in text
    assert "  + x.py\n" in text
    assert text.index("DELTAS:") < text.index("HOOKS:")
    assert text.index("COMMITS:") < text.index("DELTAS:")


def test_concurrent_writers_serialize_via_lock() -> None:
    """Two threads writing different deltas serialize and one wins; no clobber.

    The lock guarantees both writes complete cleanly, the file is well-formed,
    and the contents match exactly one of the two writers' inputs (last-writer
    wins) — never a torn mix of both.
    """
    initial = (
        "NAME: my_cl\n"
        "DESCRIPTION:\n"
        "  Test\n"
        "STATUS: Ready\n"
        "COMMITS:\n"
        "  (1) initial\n"
        "HOOKS:\n"
        "  cmd\n"
    )
    path = _write_tmp(initial)
    try:
        deltas_a = [DeltaEntry(path="thread_a.py", change_type="A")]
        deltas_b = [DeltaEntry(path="thread_b.py", change_type="M")]

        def writer(key: str, deltas: list[DeltaEntry], out: dict[str, bool]) -> None:
            out[key] = update_changespec_deltas_field(path, "my_cl", deltas)

        for _ in range(20):
            results: dict[str, bool] = {}
            ts = [
                threading.Thread(target=writer, args=("a", deltas_a, results)),
                threading.Thread(target=writer, args=("b", deltas_b, results)),
            ]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            assert results["a"] is True
            assert results["b"] is True

            with open(path, encoding="utf-8") as f:
                content = f.read()

            # Exactly one DELTAS header
            assert content.count("DELTAS:") == 1
            # Exactly one of the two writers' content is present (last writer wins)
            has_a = "thread_a.py" in content
            has_b = "thread_b.py" in content
            assert has_a ^ has_b, (
                f"Expected exactly one writer's content, got "
                f"a={has_a} b={has_b} content={content!r}"
            )
            # Surrounding sections preserved
            assert "COMMITS:\n" in content
            assert "HOOKS:\n" in content
            assert "  (1) initial\n" in content
            assert "  cmd\n" in content
    finally:
        os.unlink(path)
        for ext in (".lock", ".edit_lock"):
            try:
                os.unlink(path + ext)
            except FileNotFoundError:
                pass
