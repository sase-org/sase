"""Refresh a long-lived runner after its dependency wait crosses code updates.

The exec replays ``sys.argv`` verbatim. Any future argv field that names a
one-shot resource must therefore be re-materialized here before exec, just as
the temporary prompt file is today.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from sase.version._git import probe_git_metadata_at_ref
from sase.version._models import HOST_DISTRIBUTION_NAME
from sase.version._sources import (
    direct_url_info,
    distribution_location,
    find_distribution,
    install_type,
    resolve_import,
    source_root,
)

RUNNER_CODE_REFRESHED_ENV = "SASE_RUNNER_CODE_REFRESHED"


def _editable_sase_source_root() -> Path | None:
    """Resolve the source checkout backing an editable sase installation."""
    warnings: list[str] = []
    try:
        distribution = find_distribution(HOST_DISTRIBUTION_NAME, warnings)
        direct_url = direct_url_info(distribution, warnings)
        resolved_install_type = (
            direct_url.install_type if direct_url else install_type(distribution)
        )
        if resolved_install_type != "editable":
            return None
        return source_root(
            source_kind="python",
            direct_url=direct_url,
            install_type=resolved_install_type,
            import_resolution=resolve_import("sase"),
            distribution_location=distribution_location(distribution),
        )
    except Exception:
        return None


def _source_code_identity(source_checkout: Path | None) -> str | None:
    """Return the checkout's full HEAD SHA, or ``None`` when unavailable."""
    if source_checkout is None:
        return None
    result = probe_git_metadata_at_ref(source_checkout, "HEAD")
    return result.metadata.commit if result.metadata is not None else None


def runner_code_identity() -> str | None:
    """Return the code identity for the editable checkout used by this process."""
    return _source_code_identity(_editable_sase_source_root())


def refresh_runner_code_after_wait(
    startup_identity: str | None,
    *,
    blocking_wait_occurred: bool,
    killed: bool,
    prompt_file: str,
    submitted_xprompt: str,
) -> None:
    """Re-exec the runner when its editable source HEAD moved during a wait.

    The one-shot guard is removed on the refreshed pass before agent execution,
    preventing nested agents from inheriting runner-internal refresh state.
    """
    already_refreshed = os.environ.pop(RUNNER_CODE_REFRESHED_ENV, None) is not None
    if already_refreshed or not blocking_wait_occurred or killed:
        return
    if startup_identity is None:
        return

    current_identity = runner_code_identity()
    if current_identity is None or current_identity == startup_identity:
        return

    print(
        "Refreshing sase runner code after dependency wait: "
        f"{startup_identity} -> {current_identity}",
        flush=True,
    )
    try:
        Path(prompt_file).write_text(submitted_xprompt, encoding="utf-8")
    except OSError as exc:
        print(
            "Warning: Skipping sase runner code refresh because the temporary "
            f"prompt file could not be restored at {prompt_file}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return

    os.environ[RUNNER_CODE_REFRESHED_ENV] = "1"
    try:
        os.execv(sys.executable, [sys.executable, *sys.argv])
    except OSError as exc:
        os.environ.pop(RUNNER_CODE_REFRESHED_ENV, None)
        try:
            os.unlink(prompt_file)
        except OSError:
            pass
        print(
            f"Warning: Failed to refresh sase runner code; continuing: {exc}",
            file=sys.stderr,
            flush=True,
        )
