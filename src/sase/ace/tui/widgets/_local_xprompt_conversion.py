"""Pure decision helpers for converting a prompt pane into a local xprompt.

The ``gX`` / ``Ctrl+G X`` prompt-local keymap turns the active prompt pane into
a local ``xprompts:`` helper stored in the prompt bar's shared frontmatter and
replaces the pane with an invocation of that helper.  Every decision the keymap
makes -- normalizing and validating the helper name, inferring its inputs from
the pane body, building the :class:`~sase.xprompt.models.XPrompt`, and rendering
the invocation skeleton -- lives here as plain logic so it can be unit-tested
without a running Textual app.

Name validation reuses the launch path's underscore-scoping rule (via
:func:`parse_local_xprompt_entries`) so a helper saved here behaves identically
to one authored in raw YAML, the Frontmatter Panel, or an xprompt ``.md`` file.
Input inference reuses :func:`sase.xprompt.jinja_inspect.inspect_template` so
known top-level globals (``root`` and friends) are never mistaken for inputs.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import re

from sase.ace.tui.widgets.xprompt_arg_assist import (
    named_args_skeleton,
    xprompt_assist_entry_from_local_xprompt,
)
from sase.xprompt.jinja_inspect import inspect_template
from sase.xprompt.loader_parsing import (
    LocalXPromptNameError,
    parse_local_xprompt_entries,
)
from sase.xprompt.models import InputArg, InputType, XPrompt
from sase.xprompt.prompt_frontmatter import LOCAL_XPROMPT_SOURCE
from sase.xprompt.raw_placeholders import (
    placeholder_input_names,
    raw_placeholder_fields,
    substitute_raw_placeholders,
)

# Same identifier rule the Frontmatter Panel's xprompt sub-form enforces.
_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True)
class _PlaceholderArgConversion:
    """A body rewritten to reference inputs derived from raw placeholders."""

    body: str
    inputs: list[InputArg]
    renames: dict[str, str]


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
    """
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


def normalize_local_xprompt_name(raw: str) -> str:
    """Return the stored local xprompt name for a user-typed *raw* value.

    Local xprompts are ``_``-scoped, so a bare ``rules`` is stored as ``_rules``.
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


def validate_local_xprompt_name(name: str, used_names: set[str]) -> str:
    """Return a validation error for *name*, or ``""`` when it is acceptable.

    *name* is the already-:func:`normalize_local_xprompt_name`-d value.  It is
    validated through the same launch-path underscore-scoping rule the
    Frontmatter Panel uses (:func:`parse_local_xprompt_entries`), then checked
    for identifier validity and rejected as a duplicate when it collides with an
    existing local helper in *used_names* -- the flow never silently overwrites a
    helper the prompt already declares.
    """
    if not name:
        return "name is required"
    try:
        parse_local_xprompt_entries({name: ""}, source_path=LOCAL_XPROMPT_SOURCE)
    except LocalXPromptNameError as exc:
        return str(exc)
    if not _NAME_RE.fullmatch(name):
        return "name must be a valid identifier"
    if name in used_names:
        return f"xprompt '{name}' already exists"
    return ""


def infer_local_xprompt_inputs(body: str) -> _PlaceholderArgConversion | None:
    """Rewrite placeholders and infer every required input for a local xprompt.

    Returns one ``TEXT`` :class:`InputArg` per undeclared variable (no default,
    so each is required), with known top-level globals filtered out by
    :func:`inspect_template`.  Placeholder-derived inputs follow those Jinja
    inputs, preserving document order within each group.  A placeholder whose
    generated name is already an undeclared Jinja variable reuses that input.

    Returns ``None`` when *body* contains invalid Jinja syntax: the caller leaves
    the pane unchanged and notifies rather than minting a helper with unreliable
    inputs.
    """
    diagnostics = inspect_template(body)
    if diagnostics.has_jinja and not diagnostics.ok:
        return None
    jinja_inputs = [
        InputArg(name=variable, type=InputType.TEXT)
        for variable in diagnostics.unknown_variables
    ]
    converted = convert_placeholders_to_inputs(
        body,
        existing=diagnostics.unknown_variables,
    )
    return _PlaceholderArgConversion(
        body=converted.body,
        inputs=[*jinja_inputs, *converted.inputs],
        renames=converted.renames,
    )


def build_local_xprompt(name: str, body: str, inputs: list[InputArg]) -> XPrompt:
    """Build the local :class:`XPrompt` stored under the prompt's ``xprompts:``.

    Stamps :data:`LOCAL_XPROMPT_SOURCE` so the result compares equal to a helper
    the launch path would parse out of the same frontmatter.
    """
    return XPrompt(
        name=name,
        content=body,
        inputs=list(inputs),
        source_path=LOCAL_XPROMPT_SOURCE,
    )


def local_xprompt_invocation_skeleton(xprompt: XPrompt) -> str:
    """Return the snippet skeleton that invokes *xprompt* in a prompt pane.

    With no inputs this is the bare ``#_name`` reference; with inputs it is a
    named-argument skeleton (``#_name(a=$1, b=$2)$0``) carrying snippet tabstops
    so expanding it through the pane's snippet engine drops the cursor onto the
    first empty argument value.
    """
    entry = xprompt_assist_entry_from_local_xprompt(xprompt.name, xprompt)
    return named_args_skeleton(entry)


__all__ = [
    "build_local_xprompt",
    "convert_placeholders_to_inputs",
    "infer_local_xprompt_inputs",
    "local_xprompt_invocation_skeleton",
    "normalize_local_xprompt_name",
    "validate_local_xprompt_name",
]
