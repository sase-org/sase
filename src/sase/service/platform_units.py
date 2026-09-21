"""Native unit identity and desired-content rendering."""

from __future__ import annotations

import hashlib
import platform
import plistlib
import shlex
from pathlib import Path

from sase.service.platform_models import PlatformKind


def platform_kind() -> PlatformKind:
    system = platform.system()
    if system == "Linux":
        return "linux"
    if system == "Darwin":
        return "darwin"
    return "unsupported"


def home_suffix(home: Path) -> str:
    digest = hashlib.sha256(str(home).encode("utf-8")).hexdigest()[:12]
    return f"home-{digest}"


def render_systemd_unit(
    executable: Path | None,
    *,
    unit_identity: str,
    env_path: Path,
    alternate_home: Path | None,
) -> str:
    exe = str(executable or "sase")
    lines = [
        "[Unit]",
        "Description=SASE service host",
        "",
        "[Service]",
        "Type=exec",
        f"ExecStart={_systemd_quote(exe)} service run",
        "Restart=on-failure",
        "RestartSec=5",
        "KillMode=mixed",
        f"Environment=SASE_SERVICE_ENV={_systemd_quote(str(env_path))}",
        f"Environment=SASE_SERVICE_UNIT={_systemd_quote(unit_identity)}",
    ]
    if alternate_home is not None:
        lines.append(f"Environment=SASE_HOME={_systemd_quote(str(alternate_home))}")
    lines.extend(
        [
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        ]
    )
    return "\n".join(lines)


def render_launchd_plist(
    executable: Path | None,
    *,
    label: str,
    env_path: Path,
    stdout_path: Path,
    stderr_path: Path,
    alternate_home: Path | None,
) -> str:
    env = {
        "SASE_SERVICE_ENV": str(env_path),
        "SASE_SERVICE_UNIT": label,
    }
    if alternate_home is not None:
        env["SASE_HOME"] = str(alternate_home)
    payload = {
        "AbandonProcessGroup": True,
        "EnvironmentVariables": env,
        "KeepAlive": {"SuccessfulExit": False},
        "Label": label,
        "ProgramArguments": [str(executable or "sase"), "service", "run"],
        "RunAtLoad": True,
        "StandardErrorPath": str(stderr_path),
        "StandardOutPath": str(stdout_path),
        "ThrottleInterval": 10,
    }
    return plistlib.dumps(payload, sort_keys=True).decode("utf-8")


def _systemd_quote(value: str) -> str:
    return shlex.quote(value)
