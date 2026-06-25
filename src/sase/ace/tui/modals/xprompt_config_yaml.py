"""Compatibility imports for xprompt YAML config insertion helpers."""

from sase.xprompt.config_yaml import generate_xprompt_yaml, insert_xprompt_into_config


def _generate_xprompt_yaml(
    name: str,
    inputs: list[tuple[str, str]],
    content: str,
) -> list[str]:
    """Backward-compatible private test helper name."""
    return generate_xprompt_yaml(name, inputs, content)


__all__ = ["_generate_xprompt_yaml", "insert_xprompt_into_config"]
