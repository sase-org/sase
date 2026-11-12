"""Config-source macro loader (built-in, plugin, user, overlay, local)."""

from typing import Any

from sase.config import load_macros_by_source

from ._loader_sources_common import namespace_macro
from .discovery_order import (
    RANK_CONFIG_BASE,
    merge_by_discovery_order,
    source_rank,
)
from .loader_parsing import parse_macro_entries
from .models import Macro


def load_macros_from_config(project: str | None = None) -> dict[str, Macro]:
    """Load macros from config sources with proper source attribution.

    Loads macros from each config source separately (built-in defaults,
    plugin default configs, user sase.yml, overlay files) so that each
    macro gets the correct source attribution instead of all being
    tagged as ``"config"``.

    When *project* is given, macros from the local ``sase/sase.yml``
    (``local_config`` source) are namespaced with ``{project}/``.

    Priority order (within config sources, later overrides earlier):
    1. Built-in ``default_config.yml``
    2. Plugin ``default_config.yml`` files
    3. User ``sase.yml``
    4. Overlay ``sase_*.yml`` files
    5. Local ``sase/sase.yml`` (root ``sase.yml`` is a legacy fallback)

    Returns:
        Dictionary mapping macro name to Macro object.
    """
    from sase.macro.local_trust import partition_config_macros

    all_macros: dict[str, Macro] = {}
    lower_macros: dict[str, Any] = {}

    sources = load_macros_by_source()
    for index, (source_label, macros_data) in enumerate(sources):
        prompt_only, _executable = partition_config_macros(
            macros_data,
            lower_macros=lower_macros,
            source=source_label,
        )
        lower_macros = {**lower_macros, **dict(macros_data)}
        parsed = parse_macro_entries(prompt_only, source_label)
        if project and source_label == "local_config":
            parsed = {
                f"{project}/{name}": namespace_macro(project, xp)
                for name, xp in parsed.items()
            }
        merge_by_discovery_order(
            all_macros,
            parsed,
            fallback_rank=source_rank(RANK_CONFIG_BASE, index, len(sources)),
        )

    return all_macros
