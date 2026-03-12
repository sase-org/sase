"""Snapshot tests for pure helper functions in ace.hooks.mutations."""

from inline_snapshot import snapshot

from sase.ace.changespec import HookEntry, HookStatusLine
from sase.ace.hooks.mutations import (
    _apply_clear_hook_suffix,
    _apply_hook_suffix_update,
    get_failed_hooks_file_path,
)


def _sl(
    entry: str = "1",
    status: str = "PASSED",
    suffix: str | None = None,
    suffix_type: str | None = None,
    summary: str | None = None,
) -> HookStatusLine:
    return HookStatusLine(
        commit_entry_num=entry,
        timestamp="250101_120000",
        status=status,
        duration="1m",
        suffix=suffix,
        suffix_type=suffix_type,
        summary=summary,
    )


class TestApplyHookSuffixUpdate:
    def test_sets_suffix_on_latest_status_line(self) -> None:
        hooks = [
            HookEntry(command="my_hook", status_lines=[_sl("1"), _sl("2")]),
        ]
        updated, was_updated = _apply_hook_suffix_update(hooks, "my_hook", "new_suffix")
        assert was_updated is True
        assert updated[0].status_lines is not None
        sl2 = updated[0].status_lines[1]
        assert sl2.suffix == snapshot("new_suffix")
        # First status line untouched
        assert updated[0].status_lines[0].suffix is None

    def test_sets_suffix_on_specific_entry_id(self) -> None:
        hooks = [
            HookEntry(command="my_hook", status_lines=[_sl("1"), _sl("2")]),
        ]
        updated, was_updated = _apply_hook_suffix_update(
            hooks, "my_hook", "targeted", entry_id="1"
        )
        assert was_updated is True
        assert updated[0].status_lines is not None
        assert updated[0].status_lines[0].suffix == snapshot("targeted")
        assert updated[0].status_lines[1].suffix is None

    def test_preserves_suffix_type_and_summary(self) -> None:
        hooks = [
            HookEntry(command="my_hook", status_lines=[_sl("1")]),
        ]
        updated, _ = _apply_hook_suffix_update(
            hooks,
            "my_hook",
            "err_msg",
            suffix_type="error",
            summary="test summary",
        )
        assert updated[0].status_lines is not None
        sl = updated[0].status_lines[0]
        assert sl.suffix_type == snapshot("error")
        assert sl.summary == snapshot("test summary")

    def test_no_match_returns_not_updated(self) -> None:
        hooks = [
            HookEntry(command="other_hook", status_lines=[_sl("1")]),
        ]
        updated, was_updated = _apply_hook_suffix_update(hooks, "my_hook", "suffix")
        assert was_updated is False

    def test_hook_without_status_lines_preserved(self) -> None:
        hooks = [
            HookEntry(command="my_hook", status_lines=None),
        ]
        updated, was_updated = _apply_hook_suffix_update(hooks, "my_hook", "suffix")
        assert was_updated is False
        assert updated[0].status_lines is None

    def test_multiple_hooks_only_target_updated(self) -> None:
        hooks = [
            HookEntry(command="hook_a", status_lines=[_sl("1")]),
            HookEntry(command="hook_b", status_lines=[_sl("1", suffix="old")]),
        ]
        updated, was_updated = _apply_hook_suffix_update(hooks, "hook_a", "new")
        assert was_updated is True
        assert updated[0].status_lines is not None
        assert updated[0].status_lines[0].suffix == snapshot("new")
        # hook_b untouched
        assert updated[1].status_lines is not None
        assert updated[1].status_lines[0].suffix == snapshot("old")


class TestApplyClearHookSuffix:
    def test_clears_latest_suffix(self) -> None:
        hooks = [
            HookEntry(
                command="my_hook",
                status_lines=[_sl("1"), _sl("2", suffix="some_suffix")],
            ),
        ]
        updated, was_cleared = _apply_clear_hook_suffix(hooks, "my_hook")
        assert was_cleared is True
        assert updated[0].status_lines is not None
        assert updated[0].status_lines[1].suffix is None

    def test_no_suffix_to_clear(self) -> None:
        hooks = [
            HookEntry(command="my_hook", status_lines=[_sl("1")]),
        ]
        updated, was_cleared = _apply_clear_hook_suffix(hooks, "my_hook")
        assert was_cleared is False

    def test_no_matching_hook(self) -> None:
        hooks = [
            HookEntry(command="other", status_lines=[_sl("1", suffix="x")]),
        ]
        updated, was_cleared = _apply_clear_hook_suffix(hooks, "my_hook")
        assert was_cleared is False
        assert updated[0].status_lines is not None
        assert updated[0].status_lines[0].suffix == snapshot("x")

    def test_hook_without_status_lines(self) -> None:
        hooks = [HookEntry(command="my_hook", status_lines=None)]
        updated, was_cleared = _apply_clear_hook_suffix(hooks, "my_hook")
        assert was_cleared is False


class TestGetFailedHooksFilePath:
    def test_finds_path_in_suffix(self, make_changespec) -> None:  # type: ignore[no-untyped-def]
        cs = make_changespec.create(
            hooks=[
                HookEntry(
                    command="check",
                    status_lines=[
                        _sl(
                            "1",
                            status="FAILED",
                            suffix="/tmp/abc_failed_hooks_xyz.txt",
                        )
                    ],
                )
            ]
        )
        assert get_failed_hooks_file_path(cs) == snapshot(
            "/tmp/abc_failed_hooks_xyz.txt"
        )

    def test_finds_path_in_summary(self, make_changespec) -> None:  # type: ignore[no-untyped-def]
        cs = make_changespec.create(
            hooks=[
                HookEntry(
                    command="check",
                    status_lines=[
                        _sl(
                            "1",
                            status="FAILED",
                            summary="see /tmp/my_failed_hooks_run1.txt for details",
                        )
                    ],
                )
            ]
        )
        assert get_failed_hooks_file_path(cs) == snapshot(
            "/tmp/my_failed_hooks_run1.txt"
        )

    def test_returns_none_when_no_hooks(self, make_changespec) -> None:  # type: ignore[no-untyped-def]
        cs = make_changespec.create(hooks=None)
        assert get_failed_hooks_file_path(cs) is None

    def test_returns_none_when_no_match(self, make_changespec) -> None:  # type: ignore[no-untyped-def]
        cs = make_changespec.create(
            hooks=[
                HookEntry(
                    command="check",
                    status_lines=[_sl("1", status="PASSED")],
                )
            ]
        )
        assert get_failed_hooks_file_path(cs) is None
