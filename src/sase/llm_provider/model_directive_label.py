"""Shortest ``%model`` spelling for a resolved provider/model pair.

Width-constrained status surfaces (the ACE top-bar launch-default pill) want the
string a user would type into ``%model`` to pin a target, not the
``PROVIDER(model)`` display form. This module is the pure-read counterpart to
:func:`sase.llm_provider.registry.format_provider_model_label`.
"""

from __future__ import annotations

from sase.llm_provider.model_alias_config import model_alias_names
from sase.llm_provider.registry import (
    format_provider_model_label,
    resolve_model_provider,
)


def format_model_directive_label(
    provider: str | None = None,
    model: str | None = None,
) -> str:
    """Return the shortest ``%model`` value that resolves to (provider, model).

    The bare model name is used only when it round-trips to this provider through
    plugin metadata and no model alias of the same name shadows it; otherwise the
    explicit ``provider/model`` form is returned. Aliases are never returned: an
    alias may be a rotating pool, so it does not denote one concrete target.

    Never raises: any probe failure degrades to the explicit spelling.
    """
    if not model:
        return format_provider_model_label(provider, model)
    if not provider:
        return model

    try:
        # A round trip through the resolver implies ``model_to_provider_map()``
        # positively maps the bare name to ``provider``: an unmapped name comes
        # back as ``(None, model)`` and would only route via the ambient default
        # provider, which is not a stable spelling. ``consume=False`` keeps this
        # display-path probe from advancing a load-balanced pool's cursor.
        if model not in model_alias_names() and resolve_model_provider(
            model, consume=False
        ) == (provider, model):
            return model
    except Exception:
        pass
    return f"{provider}/{model}"
