"""Configuration for the lumberjack-based axe architecture.

Loads lumberjack definitions from the ``axe:`` section of the merged
config (default_config.yml → sase.yml → overlays).  Defaults are now
guaranteed by the base config layer in ``default_config.yml``.
"""

from dataclasses import dataclass, field

from sase.config import load_merged_config


@dataclass
class ChopConfig:
    """Configuration for a single chop (name + description)."""

    name: str
    description: str
    agent: str | None = None
    run_every: int = 1
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class LumberjackConfig:
    """Configuration for a single lumberjack."""

    name: str
    interval: int
    chops: list[ChopConfig] = field(default_factory=list)

    @property
    def chop_names(self) -> list[str]:
        """Return just the chop names as strings."""
        return [c.name for c in self.chops]


@dataclass
class AxeConfig:
    """Top-level axe configuration with lumberjack definitions."""

    max_hook_runners: int = 3
    max_agent_runners: int = 3
    max_agent_retries: int = 3
    agent_retry_delay_seconds: int = 900
    zombie_timeout_seconds: int = 7200
    query: str = ""
    chop_script_dirs: list[str] = field(default_factory=list)
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
        raw_chops = cfg.get("chops", [])
        chops: list[ChopConfig] = []
        for entry in raw_chops:
            if isinstance(entry, dict):
                raw_run_every = entry.get("run_every", 1)
                run_every = (
                    raw_run_every
                    if isinstance(raw_run_every, int) and raw_run_every >= 1
                    else 1
                )
                raw_env = entry.get("env", {})
                env = (
                    {str(k): str(v) for k, v in raw_env.items()}
                    if isinstance(raw_env, dict)
                    else {}
                )
                chops.append(
                    ChopConfig(
                        name=entry["name"],
                        description=entry.get("description", ""),
                        agent=entry.get("agent") or entry.get("xprompt"),
                        run_every=run_every,
                        env=env,
                    )
                )
            elif isinstance(entry, str):
                chops.append(ChopConfig(name=entry, description=""))
        result[name] = LumberjackConfig(
            name=name,
            interval=cfg.get("interval", 1),
            chops=chops,
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

    max_hook_runners = axe_data.get("max_hook_runners", 3)
    max_agent_runners = axe_data.get("max_agent_runners", 3)
    max_agent_retries = axe_data.get("max_agent_retries", 3)
    agent_retry_delay = axe_data.get("agent_retry_delay_seconds", 900)
    zombie_timeout = axe_data.get("zombie_timeout_seconds", 7200)
    query = axe_data.get("query", "")
    chop_script_dirs = axe_data.get("chop_script_dirs", [])

    raw_lumberjacks = axe_data.get("lumberjacks")
    if isinstance(raw_lumberjacks, dict):
        lumberjacks = _parse_lumberjacks(raw_lumberjacks)
    else:
        lumberjacks = {}

    return AxeConfig(
        max_hook_runners=max_hook_runners,
        max_agent_runners=max_agent_runners,
        max_agent_retries=max_agent_retries,
        agent_retry_delay_seconds=agent_retry_delay,
        zombie_timeout_seconds=zombie_timeout,
        query=query,
        chop_script_dirs=chop_script_dirs,
        lumberjacks=lumberjacks,
    )
