"""Configuration reader for the LLM provider layer."""

from typing import Any

from sase.config import load_merged_config


def get_llm_provider_config() -> dict[str, Any]:
    """Read the ``llm_provider`` section from ``sase.yml``.

    Looks for ``~/.config/sase/sase.yml`` and returns the ``llm_provider``
    section, or an empty dict if not found.

    Returns:
        The llm_provider configuration dict.
    """
    try:
        data = load_merged_config()

        if not isinstance(data, dict):
            return {}

        return data.get("llm_provider", {}) or {}
    except Exception:
        return {}
