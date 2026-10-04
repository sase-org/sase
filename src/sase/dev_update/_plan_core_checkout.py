"""Find the local sase-core checkout associated with a host install."""

from __future__ import annotations

import os
from pathlib import Path

from sase.version._models import VersionPackageRecord


def core_checkout_dir(host_record: VersionPackageRecord) -> Path | None:
    env_dir = os.environ.get("SASE_CORE_DIR")
    candidates = [Path(env_dir)] if env_dir else []
    if host_record.source_root:
        candidates.append(Path(host_record.source_root).parent / "sase-core")
    for candidate in candidates:
        if (candidate / "Cargo.toml").is_file():
            return candidate
    return None
