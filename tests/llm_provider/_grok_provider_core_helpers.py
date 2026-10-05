"""Shared helpers for Grok provider core tests."""

from __future__ import annotations

import os
import shutil
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider.grok import GrokProvider

_USAGE_ZERO = {
    "input_tokens": 0,
    "output_tokens": 0,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0,
}


def clear_grok_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Delete Grok/LLM extra-args env vars so command assertions are hermetic."""
    for name in (
        "SASE_GROK_PATH",
        "SASE_GROK_LARGE_ARGS",
        "SASE_GROK_SMALL_ARGS",
        "SASE_LLM_LARGE_ARGS",
        "SASE_LLM_SMALL_ARGS",
    ):
        monkeypatch.delenv(name, raising=False)


def invoke_and_capture(
    provider: GrokProvider,
    monkeypatch: pytest.MonkeyPatch,
    **invoke_kwargs: object,
) -> tuple[list[str], dict[str, object], MagicMock]:
    monkeypatch.setenv("SASE_GROK_PATH", "/opt/grok/bin/grok")
    with (
        patch(
            "sase.llm_provider.grok.stream_and_parse_messages_json_output"
        ) as mock_stream,
        patch("sase.llm_provider.grok.subprocess.Popen") as mock_popen,
        patch("sase.llm_provider.grok.provider_timer"),
    ):
        mock_process = MagicMock()
        mock_popen.return_value = mock_process
        mock_stream.return_value = ("response", "", 0, dict(_USAGE_ZERO))
        provider.invoke(
            "test prompt",
            model_tier="large",
            suppress_output=True,
            **invoke_kwargs,  # type: ignore[arg-type]
        )
        return (
            list(mock_popen.call_args.args[0]),
            dict(mock_popen.call_args.kwargs),
            mock_process,
        )


def require_grok_build() -> str:
    """Return a Grok Build binary path, skipping when it is unavailable."""
    candidate = os.environ.get("SASE_GROK_PATH") or shutil.which("grok")
    if candidate is None:
        pytest.skip("Grok Build binary not on PATH")

    result = subprocess.run(
        [candidate, "--version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if not result.stdout.startswith("grok "):
        pytest.skip("PATH grok is not Grok Build")
    return candidate
