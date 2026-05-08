from __future__ import annotations

from pathlib import Path

from sase.ace.tui.graphics.viewer import ArtifactImageArea, kitten_icat_command


_TEST_IMAGE_AREA = ArtifactImageArea(columns=90, rows=24)


def _test_icat_command(page: Path) -> list[str]:
    return kitten_icat_command(page, _TEST_IMAGE_AREA)
