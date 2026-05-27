"""Config normalization for chat install/update jobs."""

from __future__ import annotations

from ._chat_install_models import ChatInstallConfig


def load_chat_install_config(merged_config: object) -> ChatInstallConfig:
    """Read and normalize the ``chat_install`` merged-config section."""
    raw = (
        merged_config.get("chat_install", {}) if isinstance(merged_config, dict) else {}
    )
    if not isinstance(raw, dict):
        raw = {}

    command = raw.get("command", "")
    sync_workspace = raw.get("sync_workspace", True)
    timeout_seconds = raw.get("timeout_seconds", 900)
    restart_attempts = raw.get("restart_attempts", 3)

    return ChatInstallConfig(
        command=command.strip() if isinstance(command, str) else "",
        sync_workspace=bool(sync_workspace),
        timeout_seconds=_positive_int(timeout_seconds, 900),
        restart_attempts=_positive_int(restart_attempts, 3),
    )


def _positive_int(value: object, default: int) -> int:
    if not isinstance(value, int | str | bytes | bytearray):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
