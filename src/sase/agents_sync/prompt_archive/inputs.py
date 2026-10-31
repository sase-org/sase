"""Durable inputs a deferred restore needs to rebuild a planner prompt archive.

A planner archive is not derivable from the agent's artifacts directory alone:
the inline path publishes a plan-named document with a PLAN link and the plan
snapshot as its body, none of which the outbox row carries.  Widening the outbox
row would bump its schema and make the whole outbox unreadable to older
readers, so the inputs live in one small versioned record beside the planner's
other artifacts instead.  The row already names that directory.

The record is local-only state that a deferred restore reads back; it is never
published.  A missing, unreadable, or foreign record means "no inputs", which
keeps today's default-name restore for rows that predate it.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import tempfile
from typing import Any

log = logging.getLogger(__name__)

PROMPT_ARCHIVE_INPUTS_FILENAME = "prompt_archive_inputs.json"
PROMPT_ARCHIVE_INPUTS_VERSION = 1


@dataclass(frozen=True, slots=True)
class PromptArchiveInputs:
    """The archive arguments the inline planner publish was called with."""

    primary_revision: str
    prompt_content: str
    plan_ref: str | None = None
    prompt_name: str | None = None
    yyyymm: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "version": PROMPT_ARCHIVE_INPUTS_VERSION,
            "primary_revision": self.primary_revision,
            "plan_ref": self.plan_ref,
            "prompt_name": self.prompt_name,
            "yyyymm": self.yyyymm,
            "prompt_content": self.prompt_content,
        }


def _inputs_path(artifacts_dir: Path | str) -> Path:
    """Return where one artifacts directory keeps its archive inputs."""

    return Path(artifacts_dir) / PROMPT_ARCHIVE_INPUTS_FILENAME


def write_prompt_archive_inputs(
    artifacts_dir: Path | str,
    inputs: PromptArchiveInputs,
) -> Path:
    """Persist ``inputs`` atomically so a reader never sees a torn record."""

    path = _inputs_path(artifacts_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(inputs.to_json_dict(), indent=2, sort_keys=True) + "\n"
    handle, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(payload)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return path


def read_prompt_archive_inputs(
    artifacts_dir: Path | str,
    *,
    primary_revision: str,
) -> PromptArchiveInputs | None:
    """Load the inputs recorded for ``primary_revision``, or ``None``.

    The revision must match: an artifacts directory can also back a commit-path
    request whose revision is the agent's own commit, and plan inputs must never
    rename that archive.  Any problem reading the record degrades to ``None``
    so a corrupt file cannot make a restorable request unrecoverable.
    """

    path = _inputs_path(artifacts_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        log.warning("Ignoring unreadable prompt archive inputs at %s", path)
        return None
    if not isinstance(raw, dict) or raw.get("version") != PROMPT_ARCHIVE_INPUTS_VERSION:
        return None
    prompt_content = raw.get("prompt_content")
    if raw.get("primary_revision") != primary_revision or not isinstance(
        prompt_content, str
    ):
        return None
    return PromptArchiveInputs(
        primary_revision=primary_revision,
        prompt_content=prompt_content,
        plan_ref=_optional_str(raw.get("plan_ref")),
        prompt_name=_optional_str(raw.get("prompt_name")),
        yyyymm=_optional_str(raw.get("yyyymm")),
    )


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = [
    "PROMPT_ARCHIVE_INPUTS_FILENAME",
    "PROMPT_ARCHIVE_INPUTS_VERSION",
    "PromptArchiveInputs",
    "read_prompt_archive_inputs",
    "write_prompt_archive_inputs",
]
