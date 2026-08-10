"""Installation path for consuming cached Rust prebuild artifacts."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from sase.config.core import load_merged_config
from sase.dev_update.models import DevCommandRunner
from sase.dev_update.prebuild_cache import (
    DEFAULT_PROFILE,
    EXTENSION_FILENAME,
    LSP_BINARY_NAME,
    MISS_COMMIT_MISMATCH,
    MISS_COPY_FAILURE,
    MISS_DIGEST_MISMATCH,
    MISS_DISABLED,
    MISS_HEALTH_CHECK_FAILED,
    MISS_STAMP_MISSING,
    PROFILE_ENV,
    RustPrebuildConsumeOutcome,
    artifact_paths,
    current_provenance,
    find_matching_set,
    prebuild_miss,
    resolve_commit,
    stamp_digests_match,
)


def consume_prebuild(
    *,
    core_root: Path,
    host_root: Path,
    target_python: str,
    profile: str | None = None,
    root: Path,
    config: Mapping[str, Any] | None = None,
    run: DevCommandRunner,
    replace_file: Callable[[Path, Path], None] = os.replace,
) -> RustPrebuildConsumeOutcome:
    """Install a matching prebuilt set, or return a precise miss reason."""
    if not _prebuild_enabled(config):
        return prebuild_miss(MISS_DISABLED)
    active_profile = profile or os.environ.get(PROFILE_ENV) or DEFAULT_PROFILE
    commit = resolve_commit(core_root, "HEAD", run)
    if commit is None:
        return prebuild_miss(MISS_COMMIT_MISMATCH)
    provenance = current_provenance(
        core_root,
        core_commit=commit,
        target_python=target_python,
        profile=active_profile,
        run=run,
    )
    if provenance is None:
        return prebuild_miss(MISS_STAMP_MISSING)

    match = find_matching_set(root, provenance)
    if isinstance(match, RustPrebuildConsumeOutcome):
        return match
    set_dir, stamp = match
    artifacts = artifact_paths(set_dir, stamp)
    if artifacts is None:
        return prebuild_miss(MISS_STAMP_MISSING)
    extension_src, lsp_src = artifacts
    if not stamp_digests_match(stamp, extension_src, lsp_src):
        return prebuild_miss(MISS_DIGEST_MISMATCH)
    try:
        _install_artifacts(
            extension_src,
            lsp_src,
            core_root=core_root,
            host_root=host_root,
            target_python=target_python,
            run=run,
            replace_file=replace_file,
        )
    except OSError:
        return prebuild_miss(MISS_COPY_FAILURE)
    if not _probe_installed_extension(target_python, run):
        return prebuild_miss(MISS_HEALTH_CHECK_FAILED)
    return RustPrebuildConsumeOutcome(True, "hit", set_key=set_dir.name)


def _install_artifacts(
    extension_src: Path,
    lsp_src: Path,
    *,
    core_root: Path,
    host_root: Path,
    target_python: str,
    run: DevCommandRunner,
    replace_file: Callable[[Path, Path], None],
) -> None:
    extension_dest = (
        core_root
        / "crates"
        / "sase_core_py"
        / "python"
        / "sase_core_rs"
        / EXTENSION_FILENAME
    )
    lsp_dest = Path(target_python).parent / LSP_BINARY_NAME
    _copy_atomic(extension_src, extension_dest, replace_file=replace_file)
    _copy_atomic(lsp_src, lsp_dest, executable=True, replace_file=replace_file)
    purge = host_root / "tools" / "purge_sase_core_rs_extensions"
    result = run((target_python, str(purge)))
    if result.returncode != 0:
        raise OSError(result.stderr or result.stdout or "extension purge failed")


def _copy_atomic(
    source: Path,
    destination: Path,
    *,
    executable: bool = False,
    replace_file: Callable[[Path, Path], None] = os.replace,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        shutil.copy2(source, tmp)
        if executable:
            tmp.chmod(tmp.stat().st_mode | 0o111)
        replace_file(tmp, destination)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _probe_installed_extension(
    target_python: str,
    run: DevCommandRunner,
) -> bool:
    result = run((target_python, "-c", "import sase_core_rs"))
    return result.returncode == 0


def _prebuild_enabled(config: Mapping[str, Any] | None) -> bool:
    data = load_merged_config() if config is None else config
    ace = data.get("ace") if isinstance(data, Mapping) else None
    updates = ace.get("updates") if isinstance(ace, Mapping) else None
    if not isinstance(updates, Mapping):
        return True
    value = updates.get("prebuild_rust")
    if isinstance(value, bool):
        return value
    return True
