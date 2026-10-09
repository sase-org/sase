"""Install-context-aware reinstall remedies.

Every ``src/`` reinstall hint routes through :func:`reinstall_remedy` so the
advice matches how the running ``sase`` was installed: a uv-tool dev install
gets ``sase update`` / ``just install-dev``, a uv-tool release gets
``sase update`` / ``uv tool install --force``, a checkout ``.venv`` gets
``just install-venv``, and anything else gets a generic reinstall pointer.

The module is deliberately cheap: only ``importlib.metadata``, ``json``,
``os``, ``sys``, and the :mod:`sase.uv_tool.detect` prefix rule (reimplemented
in :func:`_default_uv_tool_dir` to avoid a circular import through the
``sase.uv_tool`` package ``__init__``). It never imports the installed
``sase`` packaging beyond its own dist metadata.
"""

from __future__ import annotations

import importlib.metadata
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Literal
from collections.abc import Mapping

#: Where the running ``sase`` came from, as classified by :func:`install_context`.
InstallContext = Literal["uv_tool_dev", "uv_tool_release", "checkout_venv", "other"]

#: Distribution name of the host package whose ``direct_url.json`` decides
#: editable vs release inside a uv tool env.
_HOST_DISTRIBUTION = "sase"

_IsFileFn = Callable[[Path], bool]
_ReadTextFn = Callable[[Path], str]


def install_context(
    *,
    sys_prefix: str | os.PathLike[str] | None = None,
    tool_dir: str | os.PathLike[str] | None = None,
    host_editable: bool | None = None,
    is_file: _IsFileFn | None = None,
    read_text: _ReadTextFn | None = None,
) -> InstallContext:
    """Classify how the running ``sase`` was installed.

    Args:
        sys_prefix: Override for ``sys.prefix`` (tests fake the prefix).
        tool_dir: Override for the uv tool directory (else ``$UV_TOOL_DIR``
            or the XDG default, mirroring uv's own resolution).
        host_editable: Override for the host's ``direct_url.json`` editable
            flag (else probed from the installed ``sase`` distribution).
        is_file: Override for ``Path.is_file`` (tests fake the filesystem).
        read_text: Override for ``Path.read_text`` (tests fake the filesystem).

    Returns:
        ``uv_tool_dev`` when the prefix is the uv tool env and the host is
        editable, ``uv_tool_release`` for any other uv tool env,
        ``checkout_venv`` when the prefix is a checkout ``.venv`` whose
        parent carries a Justfile and sase's ``pyproject.toml``, else
        ``other``.
    """
    prefix = Path(sys.prefix if sys_prefix is None else sys_prefix)
    resolved_tool_dir = (
        Path(tool_dir) if tool_dir is not None else _default_uv_tool_dir(os.environ)
    )
    if _normalize(prefix) == _normalize(resolved_tool_dir / "sase"):
        editable = host_editable if host_editable is not None else _host_is_editable()
        return "uv_tool_dev" if editable else "uv_tool_release"
    exists = is_file if is_file is not None else _is_file
    read = read_text if read_text is not None else _read_text
    if prefix.name == ".venv" and _is_checkout_dir(prefix.parent, exists, read):
        return "checkout_venv"
    return "other"


def reinstall_remedy(
    context: InstallContext | None = None,
    *,
    checkout_dir: str | os.PathLike[str] | None = None,
) -> str:
    """Return the reinstall phrase for *context* (detected live by default).

    Args:
        context: Override for :func:`install_context` (tests pin it).
        checkout_dir: Override for the checkout named in the ``checkout_venv``
            phrase (else derived from the live ``sys.prefix`` when it is a
            checkout ``.venv``, else omitted).
    """
    resolved = context if context is not None else install_context()
    if resolved == "uv_tool_dev":
        return "run `sase update` (or `just install-dev` from your sase checkout)"
    if resolved == "uv_tool_release":
        return "run `sase update` (or `uv tool install --force sase`)"
    if resolved == "checkout_venv":
        directory = (
            Path(checkout_dir) if checkout_dir is not None else _live_checkout_dir()
        )
        suffix = f" in {directory}" if directory is not None else ""
        return f"run `just install-venv`{suffix}"
    return (
        "reinstall sase in this environment "
        "(for example `uv tool install --force sase`)"
    )


def _host_is_editable() -> bool:
    """Return whether the installed ``sase`` distribution is editable."""
    try:
        direct_url = importlib.metadata.distribution(_HOST_DISTRIBUTION).read_text(
            "direct_url.json"
        )
    except (importlib.metadata.PackageNotFoundError, OSError):
        return False
    if not direct_url:
        return False
    try:
        payload = json.loads(direct_url)
    except ValueError:
        return False
    if not isinstance(payload, dict):
        return False
    dir_info = payload.get("dir_info")
    return isinstance(dir_info, dict) and dir_info.get("editable") is True


def _is_checkout_dir(
    directory: Path, is_file: _IsFileFn, read_text: _ReadTextFn
) -> bool:
    """Return whether *directory* looks like a sase checkout."""
    if not is_file(directory / "Justfile"):
        return False
    pyproject = directory / "pyproject.toml"
    if not is_file(pyproject):
        return False
    try:
        text = read_text(pyproject)
    except OSError:
        return False
    return 'name = "sase"' in text


def _live_checkout_dir() -> Path | None:
    """Return the live checkout owning ``sys.prefix``, if it is one."""
    prefix = Path(sys.prefix)
    if prefix.name != ".venv":
        return None
    try:
        if _is_checkout_dir(prefix.parent, _is_file, _read_text):
            return prefix.parent
    except OSError:
        return None
    return None


def _default_uv_tool_dir(environ: Mapping[str, str]) -> Path:
    """Mirror :func:`sase.uv_tool.detect.default_uv_tool_dir`.

    Kept local (instead of imported) because importing anything under the
    ``sase.uv_tool`` package runs its ``__init__``, which chains back into
    :mod:`sase.core.rust` — a circular import. Parity is pinned by
    ``test_install_remedy_tool_dir_matches_detect``.
    """
    override = environ.get("UV_TOOL_DIR")
    if override:
        return Path(override)
    xdg = environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "uv" / "tools"


def _is_file(path: Path) -> bool:
    return path.is_file()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalize(path: Path) -> Path:
    return Path(os.path.normpath(os.fspath(path)))


__all__ = [
    "InstallContext",
    "install_context",
    "reinstall_remedy",
]
