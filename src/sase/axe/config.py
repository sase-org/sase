"""Configuration for the new lumberjack-based axe architecture.

Loads lumberjack definitions from the ``axe:`` section of sase.yml.
When the new ``lumberjacks:`` key is absent, generates a default config
from the flat legacy fields for backward compatibility.
"""

from dataclasses import dataclass, field

from sase.config import load_merged_config

# Default lumberjack definitions matching the plan's YAML schema.
_DEFAULT_LUMBERJACKS: dict[str, dict] = {
    "hooks": {
        "interval": 1,
        "chops": [
            "hook_checks",
            "mentor_checks",
            "workflow_checks",
            "pending_checks_poll",
            "comment_zombie_checks",
            "suffix_transforms",
            "orphan_cleanup",
        ],
    },
    "checks": {
        "interval": 300,
        "chops": [
            "cl_submitted_checks",
            "stale_running_cleanup",
        ],
    },
    "comments": {
        "interval": 60,
        "chops": [
            "comment_checks",
        ],
    },
    "housekeeping": {
        "interval": 3600,
        "chops": [
            "error_digest",
        ],
    },
}


@dataclass
class LumberjackConfig:
    """Configuration for a single lumberjack."""

    name: str
    interval: int
    chops: list[str] = field(default_factory=list)


@dataclass
class AxeConfig:
    """Top-level axe configuration with lumberjack definitions."""

    max_runners: int = 5
    zombie_timeout_seconds: int = 7200
    query: str = ""
    use_legacy_axe: bool = True
    lumberjacks: dict[str, LumberjackConfig] = field(default_factory=dict)


def _parse_lumberjacks(raw: dict) -> dict[str, LumberjackConfig]:
    """Parse the ``lumberjacks:`` mapping from YAML into dataclasses.

    Args:
        raw: The raw dict from ``axe.lumberjacks`` in sase.yml.

    Returns:
        Mapping of lumberjack name to LumberjackConfig.
    """
    result: dict[str, LumberjackConfig] = {}
    for name, cfg in raw.items():
        if not isinstance(cfg, dict):
            continue
        result[name] = LumberjackConfig(
            name=name,
            interval=cfg.get("interval", 1),
            chops=cfg.get("chops", []),
        )
    return result


def _default_lumberjacks() -> dict[str, LumberjackConfig]:
    """Build default lumberjack configs from the plan's schema."""
    return _parse_lumberjacks(_DEFAULT_LUMBERJACKS)


def load_axe_config() -> AxeConfig:
    """Load axe config from sase.yml.

    If the ``lumberjacks:`` key is present, parse it directly.
    Otherwise, generate defaults from the flat legacy fields for
    backward compatibility.

    Returns:
        Fully populated AxeConfig.
    """
    data = load_merged_config()

    if not isinstance(data, dict) or "axe" not in data:
        return AxeConfig(lumberjacks=_default_lumberjacks())

    axe_data = data["axe"]
    if not isinstance(axe_data, dict):
        return AxeConfig(lumberjacks=_default_lumberjacks())

    max_runners = axe_data.get("max_runners", 5)
    zombie_timeout = axe_data.get("zombie_timeout_seconds", 7200)
    query = axe_data.get("query", "")
    use_legacy = axe_data.get("use_legacy_axe", True)

    # Parse lumberjacks if present, otherwise use defaults
    raw_lumberjacks = axe_data.get("lumberjacks")
    if isinstance(raw_lumberjacks, dict):
        lumberjacks = _parse_lumberjacks(raw_lumberjacks)
    else:
        lumberjacks = _default_lumberjacks()

    return AxeConfig(
        max_runners=max_runners,
        zombie_timeout_seconds=zombie_timeout,
        query=query,
        use_legacy_axe=use_legacy,
        lumberjacks=lumberjacks,
    )
