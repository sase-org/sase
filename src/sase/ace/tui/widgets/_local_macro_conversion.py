"""Pure decision helpers for converting a prompt pane into a local macro.

The ``gL`` / ``Ctrl+G L`` prompt-local keymap turns the active prompt pane into
a local ``macros:`` helper stored in the prompt bar's shared frontmatter and
replaces the pane with an invocation of that helper.  Every decision the keymap
makes -- normalizing and validating the helper name, inferring its inputs from
the pane body, building the :class:`~sase.macro.models.Macro`, and rendering
the invocation skeleton -- lives here as plain logic so it can be unit-tested
without a running Textual app.

Name validation reuses the launch path's underscore-scoping rule (via
:func:`parse_local_macro_entries`) so a helper saved here behaves identically
to one authored in raw YAML, the Frontmatter Panel, or a macro ``.md`` file.
Input inference reuses :func:`sase.macro.jinja_inspect.undeclared_variables`
so engine scope variables (``root``, run builtins, and friends) are never
mistaken for inputs.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import logging
import re
from typing import Any

from sase.ace.tui.widgets.macro_arg_assist import (
    named_args_skeleton,
    macro_assist_entry_from_local_macro,
)
from sase.config.core import load_merged_config
from sase.macro.jinja_assist import JinjaScope
from sase.macro.jinja_inspect import undeclared_variables
from sase.legacy_xprompt_syntax import retired_config_key
from sase.macro.loader_parsing import (
    LocalMacroNameError,
    parse_local_macro_entries,
)
from sase.macro.models import InputArg, InputType, Macro
from sase.macro.prompt_frontmatter import LOCAL_MACRO_SOURCE
from sase.macro.raw_placeholders import (
    placeholder_input_names,
    raw_placeholder_fields,
    substitute_raw_placeholders,
)

# Same identifier rule the Frontmatter Panel's macro sub-form enforces.
_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _PlaceholderArgConversion:
    """A body rewritten to reference inputs derived from raw placeholders."""

    body: str
    inputs: list[InputArg]
    renames: dict[str, str]


def _macro_placeholder_args_enabled() -> bool:
    """Return whether prompt-local macro placeholder-to-input conversion is enabled.

    Reads ``ace.prompt_inputs.macro_placeholder_args`` through the cached
    merged config. A missing, unreadable, or unparsable value falls back to
    enabled.
    """
    try:
        ace = _config_section(load_merged_config(), "ace")
        inputs = _config_section(ace, "prompt_inputs")
        # Config-layer normalization accepts the retired spelling only while
        # the compatibility flag is on and canonicalizes it before this read.
        if "macro_placeholder_args" in inputs:
            raw = inputs.get("macro_placeholder_args", True)
        else:
            retired_key = retired_config_key("macro_placeholder_args")
            raw = inputs.get(retired_key, True) if retired_key is not None else True
    except Exception:
        log.debug("macro placeholder argument toggle unavailable", exc_info=True)
        return True
    return bool(raw)


def _config_section(data: object, key: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    section = data.get(key)
    return section if isinstance(section, dict) else {}


def convert_placeholders_to_inputs(
    body: str,
    *,
    existing: Iterable[str] = (),
) -> _PlaceholderArgConversion:
    """Rewrite raw ``<placeholder>`` tags as typed Jinja input references.

    Names are allocated by the shared Rust slugging rules in document order.
    A generated name already present in *existing* is reused rather than
    redeclared, preserving an authored input's type/default/description or an
    existing undeclared Jinja variable.  Literal placeholders inside code
    zones are left untouched by the shared substitution transform.

    When ``ace.prompt_inputs.macro_placeholder_args`` is disabled, returns
    the original body without placeholder-derived inputs or renames.
    """
    if not _macro_placeholder_args_enabled():
        return _PlaceholderArgConversion(body=body, inputs=[], renames={})

    fields = raw_placeholder_fields(body)
    names = placeholder_input_names([field.text for field in fields])
    existing_names = set(existing)
    renames = {field.text: name for field, name in zip(fields, names, strict=True)}
    inputs = [
        InputArg(name=name, type=InputType.TEXT)
        for name in names
        if name not in existing_names
    ]
    replacements = {text: f"{{{{ {name} }}}}" for text, name in renames.items()}
    return _PlaceholderArgConversion(
        body=substitute_raw_placeholders(body, replacements),
        inputs=inputs,
        renames=renames,
    )


def normalize_local_macro_name(raw: str) -> str:
    """Return the stored local macro name for a user-typed *raw* value.

    Local macros are ``_``-scoped, so a bare ``rules`` is stored as ``_rules``.
    A name the user already prefixed (``_rules``) is left untouched rather than
    doubled into ``__rules``.  Surrounding whitespace is stripped; an all-blank
    value normalizes to ``""`` so the caller can reject it as missing.
    """
    name = raw.strip()
    if not name:
        return ""
    if not name.startswith("_"):
        name = "_" + name
    return name


def validate_local_macro_name(name: str, used_names: set[str]) -> str:
    """Return a validation error for *name*, or ``""`` when it is acceptable.

    *name* is the already-:func:`normalize_local_macro_name`-d value.  It is
    validated through the same launch-path underscore-scoping rule the
    Frontmatter Panel uses (:func:`parse_local_macro_entries`), then checked
    for identifier validity and rejected as a duplicate when it collides with an
    existing local helper in *used_names* -- the flow never silently overwrites a
    helper the prompt already declares.
    """
    if not name:
        return "name is required"
    try:
        parse_local_macro_entries({name: ""}, source_path=LOCAL_MACRO_SOURCE)
    except LocalMacroNameError as exc:
        return str(exc)
    if not _NAME_RE.fullmatch(name):
        return "name must be a valid identifier"
    if name in used_names:
        return f"macro '{name}' already exists"
    return ""


def infer_local_macro_inputs(body: str) -> _PlaceholderArgConversion | None:
    """Rewrite placeholders and infer every required input for a local macro.

    Returns one ``TEXT`` :class:`InputArg` per undeclared variable (no default,
    so each is required), with engine scope variables filtered out by
    :func:`undeclared_variables`, so builtins such as ``wait``,
    ``patch_name``, and ``n`` never become inferred inputs. Placeholder-derived
    inputs follow those Jinja inputs, preserving document order within each
    group. A placeholder whose generated name is already an undeclared Jinja
    variable reuses that input. Disabling
    ``ace.prompt_inputs.macro_placeholder_args`` skips only the placeholder
    rewrite; Jinja-variable input inference is unchanged.

    Returns ``None`` when *body* contains invalid Jinja syntax: the caller leaves
    the pane unchanged and notifies rather than minting a helper with unreliable
    inputs.
    """
    unknown = undeclared_variables(
        body,
        JinjaScope(kind="macro", frontmatter=None),
    )
    if unknown is None:
        return None
    jinja_inputs = [
        InputArg(name=variable, type=InputType.TEXT) for variable in unknown
    ]
    converted = convert_placeholders_to_inputs(
        body,
        existing=unknown,
    )
    return _PlaceholderArgConversion(
        body=converted.body,
        inputs=[*jinja_inputs, *converted.inputs],
        renames=converted.renames,
    )


def build_local_macro(name: str, body: str, inputs: list[InputArg]) -> Macro:
    """Build the local :class:`Macro` stored under the prompt's ``macros:``.

    Stamps :data:`LOCAL_MACRO_SOURCE` so the result compares equal to a helper
    the launch path would parse out of the same frontmatter.
    """
    return Macro(
        name=name,
        content=body,
        inputs=list(inputs),
        source_path=LOCAL_MACRO_SOURCE,
    )


def local_macro_invocation_skeleton(macro: Macro) -> str:
    """Return the snippet skeleton that invokes *macro* in a prompt pane.

    With no inputs this is the bare ``#_name`` reference; with inputs it is a
    named-argument skeleton (``#_name(a=$1, b=$2)$0``) carrying snippet tabstops
    so expanding it through the pane's snippet engine drops the cursor onto the
    first empty argument value.
    """
    entry = macro_assist_entry_from_local_macro(macro.name, macro)
    return named_args_skeleton(entry)


__all__ = [
    "build_local_macro",
    "convert_placeholders_to_inputs",
    "infer_local_macro_inputs",
    "local_macro_invocation_skeleton",
    "normalize_local_macro_name",
    "validate_local_macro_name",
]
