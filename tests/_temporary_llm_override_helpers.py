"""Shared helpers for temporary LLM override tests."""

from __future__ import annotations

import importlib.resources

from textual.app import App, ComposeResult

from sase.ace.tui.keymaps import KeymapRegistry, load_keymap_registry


def full_registry(extra_ace_cfg: dict | None = None) -> KeymapRegistry:
    """Build a registry from bundled YAML, like production AceApp does."""
    import yaml  # type: ignore[import-untyped]

    text = (
        importlib.resources.files("sase")
        .joinpath("default_config.yml")
        .read_text(encoding="utf-8")
    )
    data = yaml.safe_load(text)
    ace_cfg = data["ace"]
    if extra_ace_cfg:
        for top, val in extra_ace_cfg.items():
            base = ace_cfg.get(top, {})
            if isinstance(base, dict) and isinstance(val, dict):
                merged = dict(base)
                for k, v in val.items():
                    if (
                        k in merged
                        and isinstance(merged[k], dict)
                        and isinstance(v, dict)
                    ):
                        merged[k] = {**merged[k], **v}
                    else:
                        merged[k] = v
                ace_cfg[top] = merged
            else:
                ace_cfg[top] = val
    return load_keymap_registry(ace_cfg)


class TemporaryOverrideTestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


def flatten_help_keys(sections: list[tuple[str, list[tuple[str, str]]]]) -> set[str]:
    """Collect (key, label) pairs across all sections of a help spec."""
    out: set[str] = set()
    for _, rows in sections:
        for key, label in rows:
            out.add(f"{key}|{label}")
    return out
