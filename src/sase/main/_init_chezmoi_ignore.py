"""Maintain machine-specific entries in the chezmoi ignore list."""

from __future__ import annotations

import json
from pathlib import Path
import re
import socket
import subprocess

_VALID_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


_HOSTNAME_GUARD_RE = re.compile(r'^\{\{ if ne \.chezmoi\.hostname "([^"]+)" \}\}$')
_HOSTNAME_GUARD_END_RE = re.compile(r"^\{\{ end \}\}$")


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
    parts = list(relative_path.parts)
    if parts:
        last = parts[-1]
        if last.endswith(".tmpl") and last != ".tmpl":
            parts[-1] = last[: -len(".tmpl")]
    return "/".join(
        f".{part[4:]}" if part.startswith("dot_") else part for part in parts
    )


def parse_hostname_ignore_entries(text: str) -> dict[str, str]:
    """Return ``{target_entry: hostname}`` for generated hostname-guard stanzas.

    Only the ``ensure_machine_ignore_entry`` shape is recognized::

        {{ if ne .chezmoi.hostname "<hostname>" }}
        <entry>
        {{ end }}

    Unrelated lines and stanzas (plain entries, ``.chezmoi.fqdnHostname``
    guards, malformed or unclosed blocks) are ignored. Duplicate entries keep
    the last matching hostname.
    """
    mapping: dict[str, str] = {}
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        match = _HOSTNAME_GUARD_RE.fullmatch(lines[index].strip())
        if match is None:
            index += 1
            continue
        hostname = match.group(1)
        index += 1
        entries: list[str] = []
        while index < len(lines):
            stripped = lines[index].strip()
            if _HOSTNAME_GUARD_END_RE.fullmatch(stripped) is not None:
                break
            if stripped and not stripped.startswith("{{"):
                entries.append(stripped)
            index += 1
        if index >= len(lines):
            break
        if _VALID_HOSTNAME_RE.fullmatch(hostname) is not None:
            for entry in entries:
                mapping[entry] = hostname
        index += 1
    return mapping


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
    "parse_hostname_ignore_entries",
]
