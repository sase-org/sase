"""Configuration reader for the LLM provider layer."""

import os
from typing import Any

import yaml  # type: ignore[import-untyped]


def get_llm_provider_config() -> dict[str, Any]:
    """Read the ``llm_provider`` section from ``sase.yml``.

    Looks for ``~/.config/sase/sase.yml`` and returns the ``llm_provider``
    section, or an empty dict if not found.

    Returns:
        The llm_provider configuration dict.
    """
    config_path = os.path.expanduser("~/.config/sase/sase.yml")
    if not os.path.exists(config_path):
        return {}

    try:
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            return {}

        return data.get("llm_provider", {}) or {}
    except Exception:
        return {}
