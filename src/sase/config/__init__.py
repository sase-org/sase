"""Configuration loading and domain-specific config modules.

Re-exports the public API from ``config.core`` so that existing
``from sase.config import X`` imports continue to work.
"""

from sase.config.core import (
    CHEZMOI_HOME,
    CONFIG_DIR,
    get_use_chezmoi,
    load_merged_config,
    load_xprompts_by_source,
)

__all__ = [
    "CHEZMOI_HOME",
    "CONFIG_DIR",
    "get_use_chezmoi",
    "load_merged_config",
    "load_xprompts_by_source",
]
