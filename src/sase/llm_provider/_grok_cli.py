"""Shared Grok CLI constants and executable discovery."""

from __future__ import annotations

import os
import shutil

_GROK_PATH_ENV = "SASE_GROK_PATH"
GROK_CLI_NAME = "grok"
GROK_RULES_ARGV_BYTE_LIMIT = 120 * 1024


def resolve_grok_executable() -> str:
    """Return the Grok Build executable SASE should launch."""
    explicit_path = os.environ.get(_GROK_PATH_ENV)
    if explicit_path:
        return explicit_path

    path_result = shutil.which(GROK_CLI_NAME)
    if path_result:
        return path_result

    return GROK_CLI_NAME
