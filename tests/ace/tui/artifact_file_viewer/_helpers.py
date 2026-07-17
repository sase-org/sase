from __future__ import annotations

import re
from pathlib import Path

from sase.ace.tui.graphics.viewer import ArtifactFileImageArea, kitten_icat_command


_TEST_IMAGE_AREA = ArtifactFileImageArea(columns=90, rows=24)
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(value: str) -> str:
    return _ANSI_RE.sub("", value)


def _test_icat_command(page: Path) -> list[str]:
    return kitten_icat_command(page, _TEST_IMAGE_AREA)
