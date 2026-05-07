"""Interactive image viewer helper for TUI surfaces."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass

from .images import is_supported_image_path


@dataclass(frozen=True)
class ImageViewerResult:
    """Result returned after trying to open an image outside Textual."""

    ok: bool
    warning: str | None = None


def view_image_file(path: str) -> ImageViewerResult:
    """Open *path* with ``kitten icat`` and wait for a key before returning."""
    expanded = os.path.abspath(os.path.expanduser(path))
    if not is_supported_image_path(expanded):
        return ImageViewerResult(False, "Unsupported image type")
    if not os.path.exists(expanded):
        return ImageViewerResult(False, "Image file not found")
    if shutil.which("kitten") is None:
        return ImageViewerResult(False, "kitten executable not found")

    script = (
        'kitten icat "$1"\n'
        "status=$?\n"
        'printf "\\nPress any key to return to SASE..."\n'
        "read -r -n 1\n"
        'printf "\\n"\n'
        "exit $status\n"
    )
    result = subprocess.run(
        ["bash", "-lc", script, "sase-image-viewer", expanded],
        check=False,
    )
    if result.returncode != 0:
        return ImageViewerResult(
            False,
            f"kitten icat failed with exit code {result.returncode}",
        )
    return ImageViewerResult(True)
