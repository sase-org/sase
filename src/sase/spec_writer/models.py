"""Data models for the spec_writer subsystem."""

import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class OperationType(StrEnum):
    """Types of write operations supported by the spec writer."""

    SET_STATUS = "SET_STATUS"
    SET_CL = "SET_CL"
    SET_PARENT = "SET_PARENT"
    SET_DESCRIPTION = "SET_DESCRIPTION"
    SET_NAME = "SET_NAME"
    UPDATE_PARENT_REFERENCES = "UPDATE_PARENT_REFERENCES"


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
