"""Legacy axe scheduler configuration loading (quarantined)."""

from dataclasses import dataclass

from sase.config import load_merged_config


@dataclass
class _AxeConfig:
    """Configuration for the legacy axe scheduler."""

    full_check_interval: int = 300
    comment_check_interval: int = 60
    hook_interval: int = 1
    zombie_timeout_seconds: int = 7200
    max_runners: int = 5


def load_axe_config() -> _AxeConfig:
    """Load axe config from sase.yml, returning defaults if section missing."""
    data = load_merged_config()

    if not isinstance(data, dict) or "axe" not in data:
        return _AxeConfig()

    axe_data = data["axe"]
    if not isinstance(axe_data, dict):
        return _AxeConfig()

    return _AxeConfig(
        full_check_interval=axe_data.get(
            "full_check_interval", _AxeConfig.full_check_interval
        ),
        comment_check_interval=axe_data.get(
            "comment_check_interval", _AxeConfig.comment_check_interval
        ),
        hook_interval=axe_data.get("hook_interval", _AxeConfig.hook_interval),
        zombie_timeout_seconds=axe_data.get(
            "zombie_timeout_seconds", _AxeConfig.zombie_timeout_seconds
        ),
        max_runners=axe_data.get("max_runners", _AxeConfig.max_runners),
    )
