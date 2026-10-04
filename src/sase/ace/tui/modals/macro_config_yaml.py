"""Compatibility imports for macro YAML config insertion helpers."""

from sase.macro.config_yaml import generate_macro_yaml, insert_macro_into_config


def _generate_macro_yaml(
    name: str,
    inputs: list[tuple[str, str]],
    content: str,
) -> list[str]:
    """Backward-compatible private test helper name."""
    return generate_macro_yaml(name, inputs, content)


__all__ = ["_generate_macro_yaml", "insert_macro_into_config"]
