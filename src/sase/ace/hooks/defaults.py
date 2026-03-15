"""Default hook configuration for new ChangeSpecs."""

import os

from sase.vcs_provider.config import get_vcs_provider_config

from sase.ace.constants import _DEFAULT_REQUIRED_HOOKS


def get_required_changespec_hooks() -> tuple[str, ...]:
    """Get the required hooks for new ChangeSpecs.

    Reads ``vcs_provider.default_hooks`` from ``sase.yml``. If present and
    non-empty, returns it as a tuple.  Otherwise falls back to the built-in
    ``_DEFAULT_REQUIRED_HOOKS`` for Mercurial repos, or an empty tuple for
    git repos (which have no default hooks).

    Returns:
        Tuple of hook command strings.
    """
    config = get_vcs_provider_config()
    override = config.get("default_hooks")
    if override:
        return tuple(override)

    # The built-in defaults are hg-specific; only use them for hg repos.
    from sase.vcs_provider._registry import detect_vcs_family

    vcs_family = detect_vcs_family(os.getcwd())
    if vcs_family == "hg":
        return _DEFAULT_REQUIRED_HOOKS
    return ()
