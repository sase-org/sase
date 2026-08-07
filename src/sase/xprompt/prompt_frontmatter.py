"""Structured prompt frontmatter model + canonical YAML round-trip.

This is the deterministic, non-visual model the prompt Frontmatter Panel binds
to (Phase 2 of the prompt-frontmatter-panel epic), mirroring how
:mod:`sase.ace.tui.widgets.prompt_stack` was built as a pure state model before
the widget.  It contains **no** Textual: parsing, serialization, and accessors
are plain logic so the whole round-trip can be unit-tested without an app.

Responsibilities:

- :meth:`PromptFrontmatter.parse` rehydrates a structured model from a raw
  ``---``-delimited frontmatter block (or a bare YAML body), reusing the
  existing runtime parsers (:func:`parse_yaml_front_matter`,
  :func:`parse_inputs_from_front_matter`, :func:`parse_local_xprompt_entries`)
  so the model never reimplements parsing.
- :meth:`PromptFrontmatter.serialize` emits the **canonical** YAML form
  (including delimiters) for the parity field set (``name``, ``description``,
  ``tags``, ``input``, ``xprompts``, ``skill``, ``snippet``).  The panel owns
  this canonical form; round-tripping ``parse -> serialize -> parse`` is lossless
  for canonical forms.
- ``input`` is canonical; a user-typed ``inputs`` is accepted as an alias and
  normalized to ``input`` on parse (design decision #1).

Field/value *validation* and guidance live in ``sase-core`` (the same engine
that backs the xprompt LSP); :meth:`PromptFrontmatter.diagnostics` returns those
core diagnostics so the panel and editor never drift.  Validation is the only
thing that needs the Rust binding; parse/serialize are pure Python.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import re
from typing import TYPE_CHECKING, Any

import yaml  # type: ignore[import-untyped]

from .loader_parsing import (
    parse_inputs_from_front_matter,
    parse_local_xprompt_entries,
    parse_yaml_front_matter,
)
from .models import UNSET, InputArg, XPrompt

if TYPE_CHECKING:
    from .frontmatter_schema import FrontmatterDiagnostic

# Source identifier stamped onto local xprompts parsed out of a prompt's
# frontmatter — matches :func:`sase.agent.multi_prompt.parse_multi_prompt` so a
# model parsed here compares equal to one the launch path would build.
LOCAL_XPROMPT_SOURCE = "user-prompt"

# Canonical top-to-bottom field order, matching the core field schema
# (``frontmatter_field_schema``) and the panel's row order.  Kept local so
# serialization stays pure Python and does not require the Rust binding.
_FIELD_ORDER = ("name", "description", "tags", "input", "xprompts", "skill", "snippet")
_KNOWN_INPUT_KEYS = frozenset({"input", "inputs"})
_KNOWN_FIELDS = frozenset(_FIELD_ORDER) | _KNOWN_INPUT_KEYS


class FrontmatterValueState(StrEnum):
    """Explicit state for the schema's bool-or-payload field kinds."""

    TRUE = "true"
    FALSE = "false"
    PAYLOAD = "payload"


@dataclass(frozen=True)
class FrontmatterStateValue:
    """A bool state, or an explicitly selected string/list payload."""

    state: FrontmatterValueState
    payload: str | list[str] | None = None


@dataclass
class PromptFrontmatter:
    """Structured editing view over a prompt's YAML frontmatter.

    Mirrors the xprompt ``.md`` field set exactly (parity, not expansion).  The
    panel mutates these fields directly; :meth:`serialize` renders them back to
    the canonical YAML block stored on :class:`~sase.ace.tui.widgets.prompt_stack.PromptStackState`.

    Attributes:
        name: The ``name`` scalar, or ``None`` when unset.
        description: The ``description`` scalar, or ``None`` when unset.
        tags: Ordered list of tag strings (free-form; core does not constrain
            ad-hoc prompt tags).
        inputs: Declared ``input`` arguments as :class:`InputArg` objects.
        xprompts: Local ``xprompts`` keyed by ``_``-prefixed name.
        skill: The ``skill`` value (``bool`` / provider list / ``None``).
        snippet: The ``snippet`` value (trigger string / ``bool`` / ``None``).
    """

    name: str | None = None
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    inputs: list[InputArg] = field(default_factory=list)
    xprompts: dict[str, XPrompt] = field(default_factory=dict)
    skill: bool | list[str] | None = None
    snippet: str | bool | None = None
    # Unknown/non-parity mappings are deliberately retained.  They render as
    # read-only rows in the structured panel and remain editable in raw mode.
    extras: dict[str, Any] = field(default_factory=dict)
    # The original source is excluded from equality: it is provenance for raw
    # editing/comment warnings, not semantic frontmatter state.
    original_text: str = field(default="", repr=False, compare=False)
    has_comments: bool = field(default=False, repr=False, compare=False)

    # -- parsing --------------------------------------------------------------

    @classmethod
    def parse(cls, raw: str) -> PromptFrontmatter:
        """Build a model from a raw frontmatter block.

        Accepts the canonical ``---``-delimited block stored on the prompt
        stack, an unterminated block still being typed, or a bare YAML body
        (no delimiters).  Unknown fields and unparseable input yield an empty
        model rather than raising — the panel surfaces problems as core
        diagnostics, not exceptions.

        Args:
            raw: The frontmatter text (with or without ``---`` delimiters).

        Returns:
            The structured model.  ``input`` and the ``inputs`` alias are both
            honored, normalized to :attr:`inputs`.

        Raises:
            LocalXPromptNameError: If an ``xprompts`` entry name is not
                ``_``-prefixed (mirrors the launch path's scoping rule).
        """
        mapping = _load_mapping(raw)
        if not mapping:
            return cls()

        # `input` is canonical; accept a user-typed `inputs` as an alias.
        input_data = mapping.get("input", mapping.get("inputs"))

        xprompt_entries = mapping.get("xprompts")
        xprompts: dict[str, XPrompt] = {}
        if isinstance(xprompt_entries, dict):
            xprompts = parse_local_xprompt_entries(
                xprompt_entries, source_path=LOCAL_XPROMPT_SOURCE
            )

        return cls(
            name=_optional_str(mapping.get("name")),
            description=_optional_str(mapping.get("description")),
            tags=_parse_tags(mapping.get("tags")),
            inputs=parse_inputs_from_front_matter(input_data),
            xprompts=xprompts,
            skill=mapping.get("skill"),
            snippet=mapping.get("snippet"),
            extras={
                key: value for key, value in mapping.items() if key not in _KNOWN_FIELDS
            },
            original_text=raw.strip(),
            has_comments=_contains_yaml_comments(raw),
        )

    # -- serialization --------------------------------------------------------

    def serialize(self) -> str:
        """Render the model to the canonical ``---``-delimited YAML block.

        An empty model serializes to ``""`` so an empty panel leaves no stray
        ``---\\n---`` on the prompt.  Fields are emitted in canonical order; the
        result carries no trailing newline, matching the
        :class:`~sase.ace.tui.widgets.prompt_stack.PromptStackState` frontmatter
        contract.
        """
        mapping = self.to_mapping()
        if not mapping:
            return ""
        body = yaml.safe_dump(
            mapping,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )
        return f"---\n{body}---"

    def to_mapping(self) -> dict[str, Any]:
        """Return the canonical YAML mapping for set fields, in field order.

        Only fields that are actually set appear, so :meth:`is_empty` and
        :meth:`serialize` agree on what "empty" means.
        """
        mapping: dict[str, Any] = {}
        if self.name is not None:
            mapping["name"] = self.name
        if self.description is not None:
            mapping["description"] = self.description
        if self.tags:
            mapping["tags"] = list(self.tags)
        if self.inputs:
            mapping["input"] = {arg.name: _input_to_yaml(arg) for arg in self.inputs}
        if self.xprompts:
            mapping["xprompts"] = {
                name: _xprompt_to_yaml(xp) for name, xp in self.xprompts.items()
            }
        if self.skill is not None:
            mapping["skill"] = self.skill
        if self.snippet is not None:
            mapping["snippet"] = self.snippet
        # Defensive: enforce canonical ordering even if fields are added later.
        ordered = {key: mapping[key] for key in _FIELD_ORDER if key in mapping}
        ordered.update(self.extras)
        return ordered

    # -- queries --------------------------------------------------------------

    @property
    def is_empty(self) -> bool:
        """True when no parity field is set (serializes to ``""``)."""
        return not self.to_mapping()

    def present_fields(self) -> list[str]:
        """Canonical-order names of the fields currently set (panel rows)."""
        return list(self.to_mapping().keys())

    def field_value(self, name: str) -> Any:
        """Return a schema field value without panel-side name branching."""
        if name == "input":
            return self.inputs
        if name == "xprompts":
            return self.xprompts
        if name in self.extras:
            return self.extras[name]
        return getattr(self, name, None)

    def clear_field(self, name: str) -> None:
        """Unset a schema field or passthrough extra."""
        if name == "input":
            self.inputs.clear()
        elif name == "xprompts":
            self.xprompts.clear()
        elif name == "tags":
            self.tags.clear()
        elif name in self.extras:
            del self.extras[name]
        elif name in {"name", "description", "skill", "snippet"}:
            setattr(self, name, None)

    def value_state(self, name: str) -> FrontmatterStateValue:
        """Return explicit state/payload for ``skill`` or ``snippet``."""
        value = self.field_value(name)
        if value is True:
            return FrontmatterStateValue(FrontmatterValueState.TRUE)
        if value is False:
            return FrontmatterStateValue(FrontmatterValueState.FALSE)
        if isinstance(value, list):
            return FrontmatterStateValue(FrontmatterValueState.PAYLOAD, list(value))
        return FrontmatterStateValue(FrontmatterValueState.PAYLOAD, value)

    def set_value_state(self, name: str, value: FrontmatterStateValue) -> None:
        """Set ``skill``/``snippet`` without guessing payloads from keywords."""
        if name not in {"skill", "snippet"}:
            raise ValueError(f"{name!r} is not a bool-or-payload field")
        if value.state is FrontmatterValueState.TRUE:
            setattr(self, name, True)
        elif value.state is FrontmatterValueState.FALSE:
            setattr(self, name, False)
        else:
            setattr(self, name, value.payload)

    def diagnostics(self) -> list[FrontmatterDiagnostic]:
        """Return core validation diagnostics for the serialized frontmatter.

        Delegates to the shared ``sase-core`` engine (the same one backing the
        xprompt LSP) so panel guidance never drifts from the editor.  An empty
        model has nothing to validate and returns no diagnostics.

        Requires the ``sase_core_rs`` binding (unlike parse/serialize).
        """
        from .frontmatter_schema import validate_frontmatter

        serialized = self.serialize()
        if not serialized:
            return []
        return validate_frontmatter(serialized)

    # -- input mutators -------------------------------------------------------

    def get_input(self, name: str) -> InputArg | None:
        """Return the declared ``input`` named *name*, or ``None``."""
        for arg in self.inputs:
            if arg.name == name:
                return arg
        return None

    def set_input(self, arg: InputArg) -> None:
        """Add *arg*, replacing any existing input with the same name in place."""
        for index, existing in enumerate(self.inputs):
            if existing.name == arg.name:
                self.inputs[index] = arg
                return
        self.inputs.append(arg)

    def remove_input(self, name: str) -> bool:
        """Remove the ``input`` named *name*; return whether one was removed."""
        for index, existing in enumerate(self.inputs):
            if existing.name == name:
                del self.inputs[index]
                return True
        return False

    # -- xprompt mutators -----------------------------------------------------

    def get_xprompt(self, name: str) -> XPrompt | None:
        """Return the local ``xprompts`` entry named *name*, or ``None``."""
        return self.xprompts.get(name)

    def set_xprompt(self, xprompt: XPrompt) -> None:
        """Add or replace the local xprompt keyed by its name."""
        self.xprompts[xprompt.name] = xprompt

    def remove_xprompt(self, name: str) -> bool:
        """Remove the local xprompt named *name*; return whether one was removed."""
        if name in self.xprompts:
            del self.xprompts[name]
            return True
        return False


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _load_mapping(raw: str) -> dict[str, Any]:
    """Load *raw* frontmatter into a mapping, tolerating partial/bare input.

    Tries the canonical ``---``-delimited parse first; falls back to loading the
    text as a bare YAML document (so a block still being typed, or a delimiter-
    less body, still yields a usable mapping).  Returns ``{}`` for anything that
    is not a YAML mapping.
    """
    text = raw.strip()
    if not text:
        return {}

    if text.startswith("---"):
        front_matter, _ = parse_yaml_front_matter(raw)
        if front_matter is not None:
            return front_matter
        # Opening `---` but no closing delimiter (e.g. mid-edit): fall through
        # and let the bare loader treat `---` as a YAML document marker.

    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


_YAML_COMMENT_RE = re.compile(r"(^|\s)#")


def _contains_yaml_comments(raw: str) -> bool:
    """Best-effort detection of comments canonical YAML cannot preserve."""
    for line in raw.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            return True
        # Ignore common quoted hashes; this is intentionally conservative: a
        # false-positive warning is safer than silently losing a real comment.
        if _YAML_COMMENT_RE.search(line) and '"#' not in line and "'#" not in line:
            return True
    return False


def _optional_str(value: Any) -> str | None:
    """Coerce a scalar to ``str`` (or ``None`` when absent/null)."""
    if value is None:
        return None
    return str(value)


def _parse_tags(value: Any) -> list[str]:
    """Normalize ``tags`` from a comma-string or list into a list of strings.

    Ad-hoc prompt tags are free-form (core does not constrain them), so this
    keeps the raw strings rather than validating against the xprompt tag enum.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _input_to_yaml(arg: InputArg) -> str | dict[str, Any]:
    """Render one :class:`InputArg` to its canonical shortform YAML value.

    A bare type string when there is no default or description; otherwise a
    ``{type, default?, description?}`` mapping.  Mirrors what
    :func:`parse_inputs_from_front_matter` accepts so the value round-trips.
    """
    has_default = arg.default is not UNSET
    has_description = arg.description is not None
    has_choices = bool(arg.choices)
    if (
        not has_default
        and not has_description
        and not arg.repeatable
        and not has_choices
    ):
        return arg.type.value

    value: dict[str, Any] = {"type": arg.type.value}
    if has_default:
        value["default"] = arg.default
    if has_description:
        value["description"] = arg.description
    if arg.repeatable:
        value["repeatable"] = True
    if has_choices:
        if any(choice.label is not None for choice in arg.choices):
            value["choices"] = [
                {"value": choice.value, "label": choice.label}
                if choice.label is not None
                else {"value": choice.value}
                for choice in arg.choices
            ]
        else:
            value["choices"] = [choice.value for choice in arg.choices]
    return value


def _xprompt_to_yaml(xprompt: XPrompt) -> str | dict[str, Any]:
    """Render one :class:`XPrompt` to its canonical YAML value.

    A bare content string when the entry carries nothing but content; otherwise
    a structured mapping, emitting only the fields that differ from defaults so
    the value round-trips through :func:`parse_local_xprompt_entries`.
    """
    if (
        not xprompt.inputs
        and not xprompt.tags
        and xprompt.snippet is None
        and xprompt.description is None
        and xprompt.skill is None
        and xprompt.log_skill_use
    ):
        return xprompt.content

    value: dict[str, Any] = {"content": xprompt.content}
    if xprompt.inputs:
        value["input"] = {arg.name: _input_to_yaml(arg) for arg in xprompt.inputs}
    if xprompt.tags:
        value["tags"] = ", ".join(sorted(tag.value for tag in xprompt.tags))
    if xprompt.snippet is not None:
        value["snippet"] = xprompt.snippet
    if xprompt.description is not None:
        value["description"] = xprompt.description
    if xprompt.skill is not None:
        value["skill"] = xprompt.skill
    if not xprompt.log_skill_use:
        value["log_skill_use"] = False
    return value


__all__ = [
    "FrontmatterStateValue",
    "FrontmatterValueState",
    "PromptFrontmatter",
    "LOCAL_XPROMPT_SOURCE",
]
