"""End-to-end smoke matrix for temporary LLM provider disables."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def _fake_executable(path: Path) -> Path:
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _run_python(
    *,
    code: str,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, (
        f"child process failed with exit code {result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    return result


def test_provider_disable_fresh_process_smoke_matrix(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "PYTHONPATH": os.pathsep.join(
                [str(repo_root), env.get("PYTHONPATH", "")]
            ).rstrip(os.pathsep),
            "SASE_HOME": str(tmp_path / "sase-home"),
            "SASE_CLAUDE_PATH": str(_fake_executable(bin_dir / "claude")),
            "SASE_CODEX_PATH": str(_fake_executable(bin_dir / "codex")),
            "SASE_GROK_PATH": str(_fake_executable(bin_dir / "grok")),
        }
    )

    _run_python(
        code="""
from sase.llm_provider.temporary_override import set_alias_override
set_alias_override("medium_worker", "claude/opus", None, source="smoke")
""",
        env=env,
    )

    writer = """
from sase.llm_provider.provider_disable import disable_provider
disable_provider(PROVIDER, DURATION, source="smoke", now=1000.0)
"""
    for provider, duration in (("claude", None), ("grok", 3600.0)):
        _run_python(
            code=writer.replace("PROVIDER", repr(provider)).replace(
                "DURATION", repr(duration)
            ),
            env=env,
        )

    matrix = r"""
import json

from sase.llm_provider.alias_view import build_alias_views
from sase.llm_provider.provider_disable import (
    disable_provider_until,
    enable_provider,
    get_active_provider_disables,
)
from sase.llm_provider.registry import (
    ProviderTemporarilyDisabledError,
    get_provider,
    resolve_model_provider_with_effort,
)

disables = get_active_provider_disables(1001.0)
out = {"initial_disables": sorted(disables)}
out["smarter"] = resolve_model_provider_with_effort(
    "@smarter",
    provider_disables=disables,
)
out["smartest"] = resolve_model_provider_with_effort(
    "@smartest",
    provider_disables=disables,
)

view = next(
    view
    for view in build_alias_views(now=1001.0, provider_disables=disables)
    if view.name == "medium_worker"
)
out["paused_override"] = {
    "paused": view.is_override_paused,
    "provider": view.provider,
    "model": view.model,
}

try:
    get_provider("claude", provider_disables=disables)
except ProviderTemporarilyDisabledError as exc:
    out["direct_error"] = str(exc)
else:
    raise AssertionError("direct disabled provider request unexpectedly succeeded")

enable_provider("claude")
disables = get_active_provider_disables(1002.0)
out["after_clear_smartest"] = resolve_model_provider_with_effort(
    "@smartest",
    provider_disables=disables,
)

enable_provider("grok")
disable_provider_until("claude", 1005.0, source="smoke", now=1000.0)
out["before_expiry"] = sorted(get_active_provider_disables(1004.999))
out["at_expiry"] = sorted(get_active_provider_disables(1005.0))

print(json.dumps(out, sort_keys=True))
"""
    result = _run_python(code=matrix, env=env)
    out = json.loads(result.stdout)

    assert out["initial_disables"] == ["claude", "grok"]
    assert out["smarter"][0] == "codex"
    assert out["smartest"][0] == "codex"
    assert out["paused_override"] == {
        "paused": True,
        "provider": "codex",
        "model": "gpt-5.5",
    }
    assert "LLM provider 'claude' is temporarily disabled" in out["direct_error"]
    assert out["after_clear_smartest"][0] == "claude"
    assert out["before_expiry"] == ["claude"]
    assert out["at_expiry"] == []
