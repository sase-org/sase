"""Packaged directory-map asset loading."""

import os
from importlib import resources
from pathlib import Path

DIRECTORY_MAP_ASSET_OVERRIDE_ENV = "SASE_DIRECTORY_MAP_ASSET_OVERRIDE"


def read_directory_map_asset(package: str, filename: str) -> bytes:
    """Read a directory-map asset, honoring an explicit source override."""
    override = os.environ.get(DIRECTORY_MAP_ASSET_OVERRIDE_ENV)
    if override:
        return Path(override).expanduser().read_bytes()

    source = resources.files(package).joinpath("assets", filename)
    with resources.as_file(source) as source_path:
        return source_path.read_bytes()
