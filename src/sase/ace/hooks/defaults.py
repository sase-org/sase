"""Default hook configuration for new ChangeSpecs."""

from sase.ace.constants import _DEFAULT_REQUIRED_HOOKS
from sase.vcs_provider.config import get_vcs_provider_config


def get_required_changespec_hooks() -> tuple[str, ...]:
    """Get the required hooks for new ChangeSpecs.

    Reads ``vcs_provider.default_hooks`` from ``sase.yml``. If present and
    non-empty, returns it as a tuple.  Otherwise falls back to the built-in
    ``_DEFAULT_REQUIRED_HOOKS``.

    Returns:
        Tuple of hook command strings.
    """
    config = get_vcs_provider_config()
    override = config.get("default_hooks")
    if override:
        return tuple(override)
    return _DEFAULT_REQUIRED_HOOKS
