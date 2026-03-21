"""Default hook configuration for new ChangeSpecs."""

from sase.vcs_provider.config import get_vcs_provider_config


def get_required_changespec_hooks() -> tuple[str, ...]:
    """Get the required hooks for new ChangeSpecs.

    Reads ``vcs_provider.default_hooks`` from the merged config (sase.yml +
    plugin defaults).  VCS-specific defaults are provided by plugins (e.g.
    sase-google supplies its hooks via ``sase.yml``).

    Returns:
        Tuple of hook command strings, or empty tuple if none configured.
    """
    config = get_vcs_provider_config()
    hooks = config.get("default_hooks")
    if hooks:
        return tuple(hooks)
    return ()
