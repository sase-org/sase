"""Built-in ``builtin@commit`` finalizer execution (facade)."""

from __future__ import annotations

from sase.finalizers.commit_execution import execute_commit_finalizer
from sase.finalizers.commit_repair import run_stitch_create, run_stitch_resume
from sase.finalizers.commit_types import (
    BuiltinCommitExecution,
    BuiltinCommitFinalizerError,
    StitchCommandResult,
)

__all__ = [
    "BuiltinCommitExecution",
    "BuiltinCommitFinalizerError",
    "StitchCommandResult",
    "execute_commit_finalizer",
    "run_stitch_create",
    "run_stitch_resume",
]
