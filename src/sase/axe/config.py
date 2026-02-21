"""Configuration for the lumberjack-based axe architecture.

Loads lumberjack definitions from the ``axe:`` section of the merged
config (default_config.yml → sase.yml → overlays).  Defaults are now
guaranteed by the base config layer in ``default_config.yml``.
"""

from dataclasses import dataclass, field

from sase.config import load_merged_config


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


def load_axe_config() -> AxeConfig:
    """Load axe config from the merged config layers.

    Defaults are provided by ``default_config.yml``, so the ``axe``
    section is always present.  Inline ``.get()`` calls remain as
    safety nets.

    Returns:
        Fully populated AxeConfig.
    """
    data = load_merged_config()

    axe_data = data.get("axe")
    if not isinstance(axe_data, dict):
        return AxeConfig()

    max_runners = axe_data.get("max_runners", 5)
    zombie_timeout = axe_data.get("zombie_timeout_seconds", 7200)
    query = axe_data.get("query", "")

    raw_lumberjacks = axe_data.get("lumberjacks")
    if isinstance(raw_lumberjacks, dict):
        lumberjacks = _parse_lumberjacks(raw_lumberjacks)
    else:
        lumberjacks = {}

    return AxeConfig(
        max_runners=max_runners,
        zombie_timeout_seconds=zombie_timeout,
        query=query,
        lumberjacks=lumberjacks,
    )
