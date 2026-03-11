"""Data models for the spec_writer subsystem."""

import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class OperationType(StrEnum):
    """Types of write operations supported by the spec writer."""

    # Category 1: Field operations
    SET_STATUS = "SET_STATUS"
    SET_CL = "SET_CL"
    SET_PARENT = "SET_PARENT"
    SET_DESCRIPTION = "SET_DESCRIPTION"
    SET_NAME = "SET_NAME"
    UPDATE_PARENT_REFERENCES = "UPDATE_PARENT_REFERENCES"

    # Category 2: Hook operations
    SET_HOOKS = "SET_HOOKS"
    MERGE_HOOKS = "MERGE_HOOKS"
    ADD_HOOK = "ADD_HOOK"
    SET_HOOK_SUFFIX = "SET_HOOK_SUFFIX"
    CLEAR_HOOK_SUFFIX = "CLEAR_HOOK_SUFFIX"
    UPDATE_HOOK_SUFFIX_TYPE = "UPDATE_HOOK_SUFFIX_TYPE"
    RERUN_DELETE_HOOKS = "RERUN_DELETE_HOOKS"
    TRY_CLAIM_HOOK_FOR_FIX = "TRY_CLAIM_HOOK_FOR_FIX"

    # Category 3: Commit operations
    ADD_COMMIT_ENTRY = "ADD_COMMIT_ENTRY"
    ADD_PROPOSED_COMMIT_ENTRY = "ADD_PROPOSED_COMMIT_ENTRY"
    REJECT_PROPOSALS_AND_SET_STATUS = "REJECT_PROPOSALS_AND_SET_STATUS"
    REJECT_ALL_NEW_PROPOSALS = "REJECT_ALL_NEW_PROPOSALS"
    UPDATE_COMMIT_ENTRY_SUFFIX = "UPDATE_COMMIT_ENTRY_SUFFIX"

    # Category 4: Comment operations
    SET_COMMENTS = "SET_COMMENTS"
    ADD_COMMENT = "ADD_COMMENT"
    REMOVE_COMMENT = "REMOVE_COMMENT"

    # Category 5: Mentor operations
    SET_MENTORS = "SET_MENTORS"
    ADD_MENTOR_ENTRY = "ADD_MENTOR_ENTRY"
    SET_MENTOR_STATUS = "SET_MENTOR_STATUS"
    CLEAR_MENTOR_STATUS_LINES = "CLEAR_MENTOR_STATUS_LINES"

    # Category 6: RUNNING field operations
    CLAIM_WORKSPACE = "CLAIM_WORKSPACE"
    RELEASE_WORKSPACE = "RELEASE_WORKSPACE"
    UPDATE_RUNNING_CL_NAME = "UPDATE_RUNNING_CL_NAME"

    # Category 7: File-level operations
    ADD_CHANGESPEC = "ADD_CHANGESPEC"
    CREATE_PROJECT_FILE = "CREATE_PROJECT_FILE"
    SET_WORKSPACE_DIR = "SET_WORKSPACE_DIR"
    SET_BARE_REPO_DIR = "SET_BARE_REPO_DIR"
    RENAME_CHANGESPEC = "RENAME_CHANGESPEC"
    MARK_PROPOSAL_BROKEN = "MARK_PROPOSAL_BROKEN"

    # Category 8: Renumber operations
    RENUMBER_COMMIT_ENTRIES = "RENUMBER_COMMIT_ENTRIES"
    REWIND_COMMIT_ENTRIES = "REWIND_COMMIT_ENTRIES"


class WriteMode(StrEnum):
    """How the caller wants the write processed."""

    SYNC = "SYNC"
    ASYNC = "ASYNC"


@dataclass
class SpecWriteRequest:
    """A request to write to a project spec file."""

    project_file: str
    operation: OperationType
    params: dict
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    mode: WriteMode = WriteMode.ASYNC
    idempotency_key: str | None = None
    caller_pid: int = field(default_factory=os.getpid)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["operation"] = str(self.operation)
        d["mode"] = str(self.mode)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SpecWriteRequest":
        d = dict(d)
        d["operation"] = OperationType(d["operation"])
        d["mode"] = WriteMode(d["mode"])
        return cls(**d)


@dataclass
class SpecWriteResponse:
    """Result of processing a spec write request."""

    request_id: str
    success: bool
    duplicate: bool = False
    error: str | None = None
    result: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SpecWriteResponse":
        return cls(**d)
