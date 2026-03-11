"""Tests for sase.spec_writer.handlers."""

import os
import tempfile
from unittest.mock import patch

from sase.spec_writer.handlers import dispatch
from sase.spec_writer.handlers.fields import (
    handle_set_cl,
    handle_set_description,
    handle_set_name,
    handle_set_parent,
    handle_set_status,
    handle_update_parent_references,
)
from sase.spec_writer.models import OperationType, SpecWriteRequest

GP_CONTENT = """\
NAME: my-change
DESCRIPTION:
  Some description here.
PARENT: parent-change
CL: 12345
STATUS: OPEN
"""


def _make_gp_file(content: str = GP_CONTENT) -> str:
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
class TestHandleSetStatus:
    def test_updates_status(self, mock_commit: object) -> None:
        path = _make_gp_file()
        try:
            req = _make_request(
                path,
                OperationType.SET_STATUS,
                {"changespec_name": "my-change", "new_status": "CLOSED"},
            )
            resp = handle_set_status(req)
            assert resp.success is True
            with open(path) as f:
                content = f.read()
            assert "STATUS: CLOSED" in content
        finally:
            os.unlink(path)


@patch("sase.ace.changespec.locking._git_commit_changespec")
class TestHandleSetCl:
    def test_updates_cl(self, mock_commit: object) -> None:
        path = _make_gp_file()
        try:
            req = _make_request(
                path,
                OperationType.SET_CL,
                {"changespec_name": "my-change", "new_cl": "99999"},
            )
            resp = handle_set_cl(req)
            assert resp.success is True
            with open(path) as f:
                content = f.read()
            assert "CL: 99999" in content
        finally:
            os.unlink(path)

    def test_removes_cl(self, mock_commit: object) -> None:
        path = _make_gp_file()
        try:
            req = _make_request(
                path,
                OperationType.SET_CL,
                {"changespec_name": "my-change", "new_cl": None},
            )
            resp = handle_set_cl(req)
            assert resp.success is True
            with open(path) as f:
                content = f.read()
            assert "CL:" not in content
        finally:
            os.unlink(path)


@patch("sase.ace.changespec.locking._git_commit_changespec")
class TestHandleSetParent:
    def test_updates_parent(self, mock_commit: object) -> None:
        path = _make_gp_file()
        try:
            req = _make_request(
                path,
                OperationType.SET_PARENT,
                {"changespec_name": "my-change", "new_parent": "new-parent"},
            )
            resp = handle_set_parent(req)
            assert resp.success is True
            with open(path) as f:
                content = f.read()
            assert "PARENT: new-parent" in content
        finally:
            os.unlink(path)


@patch("sase.ace.changespec.locking._git_commit_changespec")
class TestHandleSetDescription:
    def test_updates_description(self, mock_commit: object) -> None:
        path = _make_gp_file()
        try:
            req = _make_request(
                path,
                OperationType.SET_DESCRIPTION,
                {
                    "changespec_name": "my-change",
                    "new_description": "Updated description.",
                },
            )
            resp = handle_set_description(req)
            assert resp.success is True
            with open(path) as f:
                content = f.read()
            assert "  Updated description." in content
            assert "Some description here." not in content
        finally:
            os.unlink(path)


@patch("sase.ace.changespec.locking._git_commit_changespec")
class TestHandleSetName:
    def test_renames(self, mock_commit: object) -> None:
        path = _make_gp_file()
        try:
            req = _make_request(
                path,
                OperationType.SET_NAME,
                {"old_name": "my-change", "new_name": "renamed-change"},
            )
            resp = handle_set_name(req)
            assert resp.success is True
            with open(path) as f:
                content = f.read()
            assert "NAME: renamed-change" in content
            assert "NAME: my-change" not in content
        finally:
            os.unlink(path)


@patch("sase.ace.changespec.locking._git_commit_changespec")
class TestHandleUpdateParentReferences:
    def test_updates_references(self, mock_commit: object) -> None:
        content = """\
NAME: child-1
DESCRIPTION:
  desc
PARENT: old-parent
STATUS: OPEN

NAME: child-2
DESCRIPTION:
  desc
PARENT: old-parent
STATUS: OPEN

NAME: other
DESCRIPTION:
  desc
PARENT: unrelated
STATUS: OPEN
"""
        path = _make_gp_file(content)
        try:
            req = _make_request(
                path,
                OperationType.UPDATE_PARENT_REFERENCES,
                {"old_name": "old-parent", "new_name": "new-parent"},
            )
            resp = handle_update_parent_references(req)
            assert resp.success is True
            with open(path) as f:
                result = f.read()
            assert result.count("PARENT: new-parent") == 2
            assert "PARENT: unrelated" in result
            assert "PARENT: old-parent" not in result
        finally:
            os.unlink(path)


class TestDispatch:
    @patch("sase.ace.changespec.locking._git_commit_changespec")
    def test_dispatch_valid_operation(self, mock_commit: object) -> None:
        path = _make_gp_file()
        try:
            req = _make_request(
                path,
                OperationType.SET_STATUS,
                {"changespec_name": "my-change", "new_status": "CLOSED"},
            )
            resp = dispatch(req)
            assert resp.success is True
        finally:
            os.unlink(path)

    def test_dispatch_unknown_operation(self) -> None:
        req = SpecWriteRequest(
            request_id="test-req",
            timestamp="2024-01-01T00:00:00",
            project_file="/tmp/fake.gp",
            operation=OperationType.SET_STATUS,
            params={},
        )
        # Force an unknown operation by patching
        req.operation = "UNKNOWN_OP"  # type: ignore[assignment]
        resp = dispatch(req)
        assert resp.success is False
        assert "No handler" in (resp.error or "")

    @patch("sase.ace.changespec.locking._git_commit_changespec")
    def test_dispatch_handler_error(self, mock_commit: object) -> None:
        # Pass a non-existent file to trigger an error
        req = _make_request(
            "/tmp/nonexistent_test_file.gp",
            OperationType.SET_STATUS,
            {"changespec_name": "foo", "new_status": "OPEN"},
        )
        resp = dispatch(req)
        assert resp.success is False
        assert resp.error is not None
