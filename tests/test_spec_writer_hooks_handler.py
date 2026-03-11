"""Tests for sase.spec_writer.handlers.hooks."""

import os
import tempfile
from unittest.mock import patch

from sase.spec_writer.handlers.hooks import (
    handle_add_hook,
    handle_clear_hook_suffix,
    handle_merge_hooks,
    handle_rerun_delete_hooks,
    handle_set_hook_suffix,
    handle_set_hooks,
    handle_try_claim_hook_for_fix,
    handle_update_hook_suffix_type,
)
from sase.spec_writer.models import OperationType, SpecWriteRequest

GP_HOOKS_CONTENT = """\
NAME: my-change
DESCRIPTION:
  Some description here.
HOOKS:
  test_command
      | (1) [250101_120000] PASSED (1m23s)
  other_command
      | (1) [250101_120000] FAILED (0m30s) - (!: Hook Command Failed)
STATUS: OPEN
"""

GP_NO_HOOKS_CONTENT = """\
NAME: my-change
DESCRIPTION:
  Some description here.
STATUS: OPEN
"""

GP_CLAIM_CONTENT = """\
NAME: my-change
DESCRIPTION:
  Some description here.
HOOKS:
  test_command
      | (1) [250101_120000] FAILED (1m23s) - (%: test summary here)
STATUS: OPEN
"""


def _make_gp_file(content: str = GP_HOOKS_CONTENT) -> str:
    fd, path = tempfile.mkstemp(suffix=".gp")
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


def _make_request(
    project_file: str, operation: OperationType, params: dict
) -> SpecWriteRequest:
    return SpecWriteRequest(
        request_id="test-req",
        timestamp="2024-01-01T00:00:00",
        project_file=project_file,
        operation=operation,
        params=params,
    )


@patch("sase.ace.changespec.locking._git_commit_changespec")
class TestHandleSetHooks:
    def test_sets_hooks(self, mock_commit: object) -> None:
        path = _make_gp_file(GP_NO_HOOKS_CONTENT)
        try:
            req = _make_request(
                path,
                OperationType.SET_HOOKS,
                {
                    "changespec_name": "my-change",
                    "hooks": [{"command": "new_hook", "status_lines": None}],
                },
            )
            resp = handle_set_hooks(req)
            assert resp.success is True
            with open(path) as f:
                content = f.read()
            assert "HOOKS:" in content
            assert "new_hook" in content
        finally:
            os.unlink(path)


@patch("sase.ace.changespec.locking._git_commit_changespec")
class TestHandleMergeHooks:
    def test_merges_hooks(self, mock_commit: object) -> None:
        path = _make_gp_file()
        try:
            req = _make_request(
                path,
                OperationType.MERGE_HOOKS,
                {
                    "changespec_name": "my-change",
                    "hook_updates": {
                        "test_command": {
                            "command": "test_command",
                            "status_lines": [
                                {
                                    "commit_entry_num": "1",
                                    "timestamp": "[250101_120000]",
                                    "status": "FAILED",
                                    "duration": "1m23s",
                                    "suffix": None,
                                    "suffix_type": None,
                                    "summary": None,
                                }
                            ],
                        }
                    },
                },
            )
            resp = handle_merge_hooks(req)
            assert resp.success is True
            with open(path) as f:
                content = f.read()
            assert "FAILED" in content
            # other_command should still be present (not in updates)
            assert "other_command" in content
        finally:
            os.unlink(path)


@patch("sase.ace.changespec.locking._git_commit_changespec")
class TestHandleAddHook:
    def test_adds_hook(self, mock_commit: object) -> None:
        path = _make_gp_file(GP_NO_HOOKS_CONTENT)
        try:
            req = _make_request(
                path,
                OperationType.ADD_HOOK,
                {
                    "changespec_name": "my-change",
                    "hook_command": "new_hook",
                },
            )
            resp = handle_add_hook(req)
            assert resp.success is True
            with open(path) as f:
                content = f.read()
            assert "new_hook" in content
        finally:
            os.unlink(path)

    def test_add_existing_hook_succeeds(self, mock_commit: object) -> None:
        path = _make_gp_file()
        try:
            req = _make_request(
                path,
                OperationType.ADD_HOOK,
                {
                    "changespec_name": "my-change",
                    "hook_command": "test_command",
                },
            )
            resp = handle_add_hook(req)
            assert resp.success is True
        finally:
            os.unlink(path)


@patch("sase.ace.changespec.locking._git_commit_changespec")
class TestHandleSetHookSuffix:
    def test_sets_suffix(self, mock_commit: object) -> None:
        path = _make_gp_file()
        try:
            req = _make_request(
                path,
                OperationType.SET_HOOK_SUFFIX,
                {
                    "changespec_name": "my-change",
                    "hook_command": "test_command",
                    "suffix": "ZOMBIE",
                    "suffix_type": "error",
                    "entry_id": "1",
                },
            )
            resp = handle_set_hook_suffix(req)
            assert resp.success is True
            with open(path) as f:
                content = f.read()
            assert "ZOMBIE" in content
        finally:
            os.unlink(path)

    def test_no_hooks_fails(self, mock_commit: object) -> None:
        path = _make_gp_file(GP_NO_HOOKS_CONTENT)
        try:
            req = _make_request(
                path,
                OperationType.SET_HOOK_SUFFIX,
                {
                    "changespec_name": "my-change",
                    "hook_command": "test_command",
                    "suffix": "ZOMBIE",
                },
            )
            resp = handle_set_hook_suffix(req)
            assert resp.success is False
        finally:
            os.unlink(path)


@patch("sase.ace.changespec.locking._git_commit_changespec")
class TestHandleClearHookSuffix:
    def test_clears_suffix(self, mock_commit: object) -> None:
        # The "other_command" has a suffix "Hook Command Failed" we can clear
        path = _make_gp_file()
        try:
            req = _make_request(
                path,
                OperationType.CLEAR_HOOK_SUFFIX,
                {
                    "changespec_name": "my-change",
                    "hook_command": "other_command",
                },
            )
            resp = handle_clear_hook_suffix(req)
            assert resp.success is True
            with open(path) as f:
                content = f.read()
            assert "Hook Command Failed" not in content
        finally:
            os.unlink(path)


@patch("sase.ace.changespec.locking._git_commit_changespec")
class TestHandleUpdateHookSuffixType:
    def test_updates_suffix_type(self, mock_commit: object) -> None:
        path = _make_gp_file()
        try:
            req = _make_request(
                path,
                OperationType.UPDATE_HOOK_SUFFIX_TYPE,
                {
                    "changespec_name": "my-change",
                    "hook_command": "other_command",
                    "commit_entry_num": "1",
                    "new_suffix_type": "plain",
                },
            )
            resp = handle_update_hook_suffix_type(req)
            assert resp.success is True
            with open(path) as f:
                content = f.read()
            # Suffix should now be plain (no "!:" prefix)
            assert "Hook Command Failed" in content
            assert "!:" not in content
        finally:
            os.unlink(path)


@patch("sase.ace.changespec.locking._git_commit_changespec")
class TestHandleRerunDeleteHooks:
    def test_rerun_and_delete(self, mock_commit: object) -> None:
        path = _make_gp_file()
        try:
            req = _make_request(
                path,
                OperationType.RERUN_DELETE_HOOKS,
                {
                    "changespec_name": "my-change",
                    "commands_to_rerun": ["test_command"],
                    "commands_to_delete": ["other_command"],
                    "entry_ids_to_clear": ["1"],
                },
            )
            resp = handle_rerun_delete_hooks(req)
            assert resp.success is True
            with open(path) as f:
                content = f.read()
            # other_command should be deleted
            assert "other_command" not in content
            # test_command should still exist but without status line for entry 1
            assert "test_command" in content
        finally:
            os.unlink(path)


@patch("sase.ace.changespec.locking._git_commit_changespec")
class TestHandleTryClaimHookForFix:
    def test_claims_hook(self, mock_commit: object) -> None:
        path = _make_gp_file(GP_CLAIM_CONTENT)
        try:
            req = _make_request(
                path,
                OperationType.TRY_CLAIM_HOOK_FOR_FIX,
                {
                    "changespec_name": "my-change",
                    "hook_command": "test_command",
                    "entry_id": "1",
                    "claiming_suffix": "claiming-250101_130000",
                },
            )
            resp = handle_try_claim_hook_for_fix(req)
            assert resp.success is True
            assert resp.result is not None
            assert resp.result["summary"] == "test summary here"
            with open(path) as f:
                content = f.read()
            assert "claiming-250101_130000" in content
        finally:
            os.unlink(path)

    def test_claim_wrong_status_fails(self, mock_commit: object) -> None:
        # test_command in GP_HOOKS_CONTENT has PASSED status, not FAILED
        path = _make_gp_file()
        try:
            req = _make_request(
                path,
                OperationType.TRY_CLAIM_HOOK_FOR_FIX,
                {
                    "changespec_name": "my-change",
                    "hook_command": "test_command",
                    "entry_id": "1",
                    "claiming_suffix": "claiming-250101_130000",
                },
            )
            resp = handle_try_claim_hook_for_fix(req)
            assert resp.success is False
        finally:
            os.unlink(path)
