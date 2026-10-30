"""Best-effort launch-time staging for prompt artifact references.

This module is the stable import path for prompt-artifact staging. The
implementation lives in sibling modules to keep each file under the
500-line cap, and is re-exported here:

- :mod:`sase.core.prompt_artifact_staging_stage` — file and locator staging.
- :mod:`sase.core.prompt_artifact_staging_capture` — ``@file:<path>`` capture.
- :mod:`sase.core.prompt_artifact_staging_pool` — pool storage and budget GC.
- :mod:`sase.core._prompt_artifact_staging_shared` — record type, path
  constants, and shared row helpers.
"""

from __future__ import annotations

from sase.core._prompt_artifact_staging_shared import (
    PROMPT_ARTIFACT_MANIFEST_LOCK_NAME,
    PROMPT_ARTIFACT_MANIFEST_NAME,
    PROMPT_ARTIFACT_POOL_DIR,
    PromptArtifactRecord,
)
from sase.core.prompt_artifact_staging_capture import capture_prompt_file_ref
from sase.core.prompt_artifact_staging_stage import stage_prompt_artifact


__all__ = [
    "PROMPT_ARTIFACT_MANIFEST_NAME",
    "PROMPT_ARTIFACT_POOL_DIR",
    "PromptArtifactRecord",
    "capture_prompt_file_ref",
    "stage_prompt_artifact",
]
