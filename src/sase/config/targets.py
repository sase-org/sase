"""Write-target & scope resolution for config edits.

Pure path/policy helpers used when planning and executing a config write:
chezmoi source remapping (so an edit to a home-managed file is written to the
chezmoi source, not the applied copy), the create-overlay target path, the
defaulting rules for which writable layer to target, and a thin ``chezmoi
apply`` wrapper.

No Textual imports: callable from a worker thread. The ``chezmoi apply`` helper
is side-effecting (subprocess) and must only run from a tracked background task.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from sase.config.core import CHEZMOI_HOME, CONFIG_DIR
from sase.config.inventory import ConfigInventory, ConfigSource
from sase.content_layout import chezmoi_source_path as _layout_chezmoi_source_path


def chezmoi_source_path(target: Path) -> Path:
    """Map a home-managed config path to its chezmoi source path.

    chezmoi encodes a dotfile/dir whose name starts with ``.`` using a
    ``dot_`` prefix, rooted at ``~/.local/share/chezmoi/home``. For example
    ``~/.config/sase/sase.yml`` maps to
    ``~/.local/share/chezmoi/home/dot_config/sase/sase.yml`` (the same scheme
    used by the xprompt location modal). A path that is not under ``$HOME`` is
    not chezmoi-managed and is returned unchanged.
    """
    return _layout_chezmoi_source_path(
        target,
        home_root=Path.home(),
        source_root=CHEZMOI_HOME,
    )


def resolve_write_path(file: str | None, *, use_chezmoi: bool) -> Path | None:
    """Resolve the actual file an edit is written to.

    When *use_chezmoi* is enabled, home-managed targets are remapped to their
    chezmoi source (see :func:`chezmoi_source_path`); project-local files
    outside ``$HOME`` are never remapped. Returns ``None`` when *file* is
    ``None`` (no file-backed target, e.g. a package-default layer).
    """
    if file is None:
        return None
    target = Path(file)
    if use_chezmoi:
        return chezmoi_source_path(target)
    return target


def overlay_config_path(name: str) -> Path:
    """Return the user-overlay path for *name* (the create-overlay target).

    Normalizes to the ``sase_<name>.yml`` convention under the user config
    directory, accepting names already carrying the prefix and/or extension.
    """
    raw = name.strip()
    if not raw or raw in {".", ".."} or "/" in raw or "\\" in raw:
        raise ValueError("overlay name must be a single filename stem")
    stem = raw if raw.startswith("sase_") else f"sase_{raw}"
    if not stem.endswith(".yml"):
        stem = f"{stem}.yml"
    # Resolve through the live core module so tests and embedded frontends that
    # redirect the config root keep this helper aligned with config loading.
    from sase.config import core as config_core

    return config_core.CONFIG_DIR / stem


def _writable_sources(inventory: ConfigInventory) -> list[ConfigSource]:
    """Return the writable source rows (candidate write targets), in order."""
    return [src for src in inventory.sources if src.writable]


def _existing_writable_sources(inventory: ConfigInventory) -> list[ConfigSource]:
    """Return the writable source rows whose file already exists."""
    return [src for src in inventory.sources if src.writable and src.exists]


def default_target_layer(
    inventory: ConfigInventory, *, force_explicit: bool = False
) -> str | None:
    """Pick a sensible default writable target layer name.

    Defaulting rules (from the research):

    - When *force_explicit* (e.g. editing a list-valued field, where the
      replace-vs-concatenate consequence differs per layer), return ``None`` so
      the caller forces an explicit choice.
    - A single existing mutable source → target it.
    - Otherwise fall back to the user base layer, then to the first writable
      source, then ``None`` when nothing is writable.
    """
    if force_explicit:
        return None
    existing = _existing_writable_sources(inventory)
    if len(existing) == 1:
        return existing[0].name
    for src in inventory.sources:
        if src.writable and src.kind == "user":
            return src.name
    writable = _writable_sources(inventory)
    return writable[0].name if writable else None


def apply_chezmoi(
    path: Path | str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``chezmoi apply --force`` (optionally scoped to a single *path*).

    Applies are always forced so they stay non-interactive: chezmoi never pauses
    for a confirmation prompt on a diverged destination (these run as captured
    subprocesses with no interactive stdin). When *path* is given it is a home
    (target) path, not a chezmoi source path; ``~`` is expanded so chezmoi always
    receives an absolute home path it can resolve.

    Side-effecting subprocess; only ever call from a tracked background task.
    Returns the completed process so the caller can surface stdout/stderr; a
    non-zero exit is not raised here.
    """
    cmd = ["chezmoi", "apply", "--force"]
    if path is not None:
        cmd.append(str(Path(path).expanduser()))
    return subprocess.run(cmd, capture_output=True, text=True, check=False)
