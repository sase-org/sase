"""Handoff-aware declaration readout for ``sase instructions readout``.

Per provider and delivery mode, finished root runs are classified as
accepted, plan handoff, monitor handoff (prepared or plain), other
recognized handoff, declaration not required, miss, or unknown. Memory
reads are joined per run. The JSON document carries ``schema_version: 1``.

Python gathers staged records/receipts, host lifecycle facts, declaration
evidence, prepared-intent evidence, and bounded legacy tail strings. Class
precedence belongs to the Rust core through
``sase.core.instruction_readout``; this module never reimplements it.

Facade preserving the original public import path; the implementation now
lives in :mod:`sase.instructions._readout_classify` and
:mod:`sase.instructions._readout_build`, with helpers shared by more than
one of those modules as public names in the already-private
:mod:`sase.instructions._readout_shared`.
"""

from __future__ import annotations

from sase.instructions._readout_build import build_readout, render_readout_table
from sase.instructions._readout_shared import (
    ACCEPTED,
    CLASSES,
    EXPLICIT,
    LEGACY,
    MISS,
    MODES,
    MONITOR_PLAIN,
    MONITOR_PREPARED,
    NONE,
    NOT_REQUIRED,
    OTHER_HANDOFF,
    PLAN_HANDOFF,
    READOUT_SCHEMA_VERSION,
    TAIL_SCAN_BYTES,
    UNKNOWN,
)

__all__ = [
    "ACCEPTED",
    "CLASSES",
    "EXPLICIT",
    "LEGACY",
    "MISS",
    "MODES",
    "MONITOR_PLAIN",
    "MONITOR_PREPARED",
    "NONE",
    "NOT_REQUIRED",
    "OTHER_HANDOFF",
    "PLAN_HANDOFF",
    "READOUT_SCHEMA_VERSION",
    "TAIL_SCAN_BYTES",
    "UNKNOWN",
    "build_readout",
    "render_readout_table",
]
