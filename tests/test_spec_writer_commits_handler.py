"""Tests for sase.spec_writer.handlers.commits."""

import os
import tempfile
from unittest.mock import patch

from sase.spec_writer.handlers.commits import (
    handle_add_commit_entry,
    handle_add_proposed_commit_entry,
    handle_reject_all_new_proposals,
    handle_reject_proposals_and_set_status,
    handle_update_commit_entry_suffix,
)
from sase.spec_writer.models import OperationType, SpecWriteRequest

GP_COMMITS_CONTENT = """\
NAME: my-change
DESCRIPTION:
  Some description here.
COMMITS:
  (1) Initial commit
  (2) Second commit
STATUS: OPEN
"""

GP_NO_COMMITS_CONTENT = """\
NAME: my-change
DESCRIPTION:
  Some description here.
STATUS: OPEN
"""

GP_PROPOSALS_CONTENT = """\
NAME: my-change
DESCRIPTION:
  Some description here.
COMMITS:
  (1) Initial commit
  (1a) Proposed fix - (!: NEW PROPOSAL)
  (1b) Another proposal - (!: NEW PROPOSAL)
STATUS: OPEN
"""

GP_SUFFIX_CONTENT = """\
NAME: my-change
DESCRIPTION:
  Some description here.
COMMITS:
  (1) Initial commit
  (1a) Proposed fix - (!: NEW PROPOSAL)
STATUS: OPEN
"""


def _make_gp_file(content: str = GP_COMMITS_CONTENT) -> str:
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
class TestHandleAddCommitEntry:
    def test_adds_entry(self, mock_commit: object) -> None:
        path = _make_gp_file()
        try:
            req = _make_request(
                path,
                OperationType.ADD_COMMIT_ENTRY,
                {"cl_name": "my-change", "note": "Third commit"},
            )
            resp = handle_add_commit_entry(req)
            assert resp.success is True
            with open(path) as f:
                content = f.read()
            assert "(3) Third commit" in content
        finally:
            os.unlink(path)

    def test_adds_first_entry(self, mock_commit: object) -> None:
        path = _make_gp_file(GP_NO_COMMITS_CONTENT)
        try:
            req = _make_request(
                path,
                OperationType.ADD_COMMIT_ENTRY,
                {"cl_name": "my-change", "note": "First commit"},
            )
            resp = handle_add_commit_entry(req)
            assert resp.success is True
            with open(path) as f:
                content = f.read()
            assert "COMMITS:" in content
            assert "(1) First commit" in content
        finally:
            os.unlink(path)


@patch("sase.ace.changespec.locking._git_commit_changespec")
class TestHandleAddProposedCommitEntry:
    def test_adds_proposal(self, mock_commit: object) -> None:
        path = _make_gp_file()
        try:
            req = _make_request(
                path,
                OperationType.ADD_PROPOSED_COMMIT_ENTRY,
                {"cl_name": "my-change", "note": "Proposed fix"},
            )
            resp = handle_add_proposed_commit_entry(req)
            assert resp.success is True
            assert resp.result is not None
            assert resp.result["entry_id"] == "2a"
            with open(path) as f:
                content = f.read()
            assert "(2a) Proposed fix - (!: NEW PROPOSAL)" in content
        finally:
            os.unlink(path)


@patch("sase.ace.changespec.locking._git_commit_changespec")
class TestHandleRejectProposalsAndSetStatus:
    def test_rejects_and_sets_status(self, mock_commit: object) -> None:
        path = _make_gp_file(GP_PROPOSALS_CONTENT)
        try:
            req = _make_request(
                path,
                OperationType.REJECT_PROPOSALS_AND_SET_STATUS,
                {"cl_name": "my-change", "final_status": "Mailed"},
            )
            resp = handle_reject_proposals_and_set_status(req)
            assert resp.success is True
            with open(path) as f:
                content = f.read()
            assert "STATUS: Mailed" in content
            assert "(~!: NEW PROPOSAL)" in content
            assert "(!: NEW PROPOSAL)" not in content
        finally:
            os.unlink(path)


@patch("sase.ace.changespec.locking._git_commit_changespec")
class TestHandleRejectAllNewProposals:
    def test_rejects_proposals(self, mock_commit: object) -> None:
        path = _make_gp_file(GP_PROPOSALS_CONTENT)
        try:
            req = _make_request(
                path,
                OperationType.REJECT_ALL_NEW_PROPOSALS,
                {"cl_name": "my-change"},
            )
            resp = handle_reject_all_new_proposals(req)
            assert resp.success is True
            assert resp.result is not None
            assert resp.result["rejected_count"] == 2
            with open(path) as f:
                content = f.read()
            assert content.count("(~!: NEW PROPOSAL)") == 2
            assert "(!: NEW PROPOSAL)" not in content
        finally:
            os.unlink(path)

    def test_no_proposals_returns_zero(self, mock_commit: object) -> None:
        path = _make_gp_file()
        try:
            req = _make_request(
                path,
                OperationType.REJECT_ALL_NEW_PROPOSALS,
                {"cl_name": "my-change"},
            )
            resp = handle_reject_all_new_proposals(req)
            assert resp.success is True
            assert resp.result is not None
            assert resp.result["rejected_count"] == 0
        finally:
            os.unlink(path)


@patch("sase.ace.changespec.locking._git_commit_changespec")
class TestHandleUpdateCommitEntrySuffix:
    def test_removes_suffix(self, mock_commit: object) -> None:
        path = _make_gp_file(GP_SUFFIX_CONTENT)
        try:
            req = _make_request(
                path,
                OperationType.UPDATE_COMMIT_ENTRY_SUFFIX,
                {
                    "cl_name": "my-change",
                    "entry_id": "1a",
                    "new_suffix_type": "remove",
                },
            )
            resp = handle_update_commit_entry_suffix(req)
            assert resp.success is True
            with open(path) as f:
                content = f.read()
            assert "(1a) Proposed fix\n" in content
            assert "NEW PROPOSAL" not in content
        finally:
            os.unlink(path)

    def test_rejects_suffix(self, mock_commit: object) -> None:
        path = _make_gp_file(GP_SUFFIX_CONTENT)
        try:
            req = _make_request(
                path,
                OperationType.UPDATE_COMMIT_ENTRY_SUFFIX,
                {
                    "cl_name": "my-change",
                    "entry_id": "1a",
                    "new_suffix_type": "reject",
                },
            )
            resp = handle_update_commit_entry_suffix(req)
            assert resp.success is True
            with open(path) as f:
                content = f.read()
            assert "(~!: NEW PROPOSAL)" in content
        finally:
            os.unlink(path)

    def test_invalid_suffix_type_fails(self, mock_commit: object) -> None:
        path = _make_gp_file(GP_SUFFIX_CONTENT)
        try:
            req = _make_request(
                path,
                OperationType.UPDATE_COMMIT_ENTRY_SUFFIX,
                {
                    "cl_name": "my-change",
                    "entry_id": "1a",
                    "new_suffix_type": "invalid",
                },
            )
            resp = handle_update_commit_entry_suffix(req)
            assert resp.success is False
        finally:
            os.unlink(path)
