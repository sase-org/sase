"""Best-effort host display-version resolution for UI surfaces."""

from __future__ import annotations

from sase.version._collector import collect_package_record
from sase.version._models import HOST_DISTRIBUTION_NAME


def host_display_version() -> str | None:
    """Return the resolved ``sase`` host display version, or ``None``.

    Reuses the full :func:`collect_package_record` version-resolution stack so
    the result covers every install shape: wheel/uv-tool installs resolve to the
    distribution version (no git probe), while editable installs additionally
    get a git-derived dev suffix (e.g. ``0.8.0+3.g084a6a2.dirty``).

    The collector's ``"<unknown>"`` sentinel is normalized to ``None`` so callers
    can fall back cleanly.

    Note:
        For editable installs this blocks on ``git`` subprocesses, so UI callers
        MUST invoke it off the event loop (e.g. via ``asyncio.to_thread``).
    """
    display_version = collect_package_record(
        HOST_DISTRIBUTION_NAME,
        role="host",
        import_module="sase",
        source_kind="python",
    ).display_version
    if display_version == "<unknown>":
        return None
    return display_version
