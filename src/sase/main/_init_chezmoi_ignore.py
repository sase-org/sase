"""Maintain machine-specific entries in the chezmoi ignore list."""

from __future__ import annotations

import json
from pathlib import Path
import re
import socket
import subprocess

_VALID_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def chezmoi_target_entry(
    source_path: Path,
    *,
    chezmoi_home: Path,
) -> str | None:
    """Return the target-relative path represented by a chezmoi source path."""
    try:
        relative_path = source_path.relative_to(chezmoi_home)
    except ValueError:
        return None
    return "/".join(
        f".{part[4:]}" if part.startswith("dot_") else part
        for part in relative_path.parts
    )


def _run_chezmoi_data() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["chezmoi", "data", "--format=json"],
        capture_output=True,
        text=True,
        check=False,
    )


def chezmoi_hostname() -> str | None:
    """Return the short hostname used by chezmoi template evaluation."""
    hostname: str | None = None
    try:
        result = _run_chezmoi_data()
    except FileNotFoundError:
        result = None
    if result is not None and result.returncode == 0:
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            chezmoi_data = data.get("chezmoi")
            if isinstance(chezmoi_data, dict):
                candidate = chezmoi_data.get("hostname")
                if isinstance(candidate, str) and candidate:
                    hostname = candidate

    if hostname is None:
        hostname = socket.gethostname().split(".", 1)[0]
    if not hostname or _VALID_HOSTNAME_RE.fullmatch(hostname) is None:
        return None
    return hostname


def ensure_machine_ignore_entry(
    *,
    chezmoi_home: Path,
    entry: str,
    hostname: str,
) -> Path | None:
    """Append a hostname guard for ``entry`` unless one already exists."""
    ignore_path = chezmoi_home / ".chezmoiignore"
    current_text = (
        ignore_path.read_text(encoding="utf-8") if ignore_path.exists() else ""
    )
    if any(line.strip() == entry for line in current_text.splitlines()):
        return None

    normalized_text = current_text.rstrip("\n")
    prefix = f"{normalized_text}\n" if current_text else ""
    stanza = f'{{{{ if ne .chezmoi.hostname "{hostname}" }}}}\n{entry}\n{{{{ end }}}}\n'
    ignore_path.parent.mkdir(parents=True, exist_ok=True)
    ignore_path.write_text(f"{prefix}{stanza}", encoding="utf-8")
    return ignore_path


__all__ = [
    "chezmoi_hostname",
    "chezmoi_target_entry",
    "ensure_machine_ignore_entry",
]
