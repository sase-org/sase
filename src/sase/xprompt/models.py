"""XPrompt data models for typed prompt templates."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from sase.xprompt.tags import XPromptTag
    from sase.xprompt.workflow_models import Workflow


UNSET = object()
"""Sentinel for 'no default specified' (required input).

Use ``UNSET`` when an input has no default (i.e. it is required).
``None`` means the YAML value was explicitly ``null`` (pass-through to callee).
"""

MemoryType = Literal["core", "reference"]


class InputType(Enum):
    """Supported input argument types for XPrompt files."""

    WORD = "word"  # Single word, no whitespace
    LINE = "line"  # Single line, no newlines
    TEXT = "text"  # Multi-line text (any content)
    PATH = "path"  # Single-line file path
    AGENT = "agent"  # Agent name, same value rules as word
    INT = "int"
    BOOL = "bool"
    FLOAT = "float"
    ENUM = "enum"  # One of a declared set of choices
    CODE = "code"  # Structured source plus language.


class OutputType(Enum):
    """Supported output field types for XPrompt output schemas."""

    WORD = "word"  # Single word, no whitespace
    LINE = "line"  # Single line, no newlines
    TEXT = "text"  # Multi-line text (any content)
    PATH = "path"  # Single-line file path (existence not checked)
    BOOL = "bool"  # Boolean value
    INT = "int"  # Integer value
    FLOAT = "float"  # Floating point value


@dataclass
class OutputSpec:
    """Output specification for validating agent responses.

    Attributes:
        type: The output format type (e.g., "json_schema").
        schema: The schema definition (e.g., JSON Schema dict for json_schema type).
    """

    type: str
    schema: dict[str, Any]


class XPromptValidationError(Exception):
    """Raised when input validation fails."""

    pass


@dataclass(frozen=True)
class InputChoice:
    """One declared value of an ``InputType.ENUM`` input.

    Attributes:
        value: The exact string a caller must supply to select this choice.
        label: Optional human-readable display text for the choice.
    """

    value: str
    label: str | None = None


@dataclass
class InputArg:
    """Definition of an input argument for an XPrompt.

    Attributes:
        name: The argument name (used for named args like `name=value`).
        type: The expected type of the argument value.
        default: Default value if argument is not provided.
            ``UNSET`` means required (no default).
            ``None`` means null/pass-through (use callee's default).
        is_step_input: True for implicit step inputs (generated from step outputs).
        output_schema: For step inputs, the output schema to validate against.
        description: Optional human-readable description of the input.
        repeatable: Whether this final positional input consumes all remaining
            positional values as an ordered list.
        choices: Declared values for an ``InputType.ENUM`` input. Required and
            non-empty for ``ENUM``; must be empty for every other type.
    """

    name: str
    type: InputType = InputType.LINE
    default: Any = UNSET
    is_step_input: bool = False
    output_schema: OutputSpec | None = None
    description: str | None = None
    repeatable: bool = False
    choices: tuple[InputChoice, ...] = ()

    def __post_init__(self) -> None:
        if self.type is InputType.ENUM and not self.choices:
            raise XPromptValidationError(
                f"Argument '{self.name}' has type 'enum' but declares no choices"
            )
        if self.type is not InputType.ENUM and self.choices:
            raise XPromptValidationError(
                f"Argument '{self.name}' declares choices but is not type 'enum'"
            )
        seen_values: set[str] = set()
        for choice in self.choices:
            if choice.value in seen_values:
                raise XPromptValidationError(
                    f"Argument '{self.name}' declares duplicate choice "
                    f"value '{choice.value}'"
                )
            seen_values.add(choice.value)

    def validate_and_convert(self, value: str) -> Any:
        """Validate and convert a string value to the declared type.

        Args:
            value: The string value to convert.

        Returns:
            The converted value in the appropriate type.

        Raises:
            XPromptValidationError: If value cannot be converted to declared type.
        """
        if self.type in {InputType.WORD, InputType.AGENT}:
            if not value:
                raise XPromptValidationError(
                    f"Argument '{self.name}' expects a non-empty word"
                )
            if any(c.isspace() for c in value):
                raise XPromptValidationError(
                    f"Argument '{self.name}' expects word (no spaces), got '{value}'"
                )
            return value
        elif self.type == InputType.LINE:
            if "\n" in value:
                raise XPromptValidationError(
                    f"Argument '{self.name}' expects line (no newlines), "
                    f"got value with newlines"
                )
            return value
        elif self.type == InputType.TEXT:
            return value  # No validation
        elif self.type == InputType.PATH:
            if "\n" in value:
                raise XPromptValidationError(
                    f"Argument '{self.name}' expects single-line path "
                    f"(no newlines), got value with newlines"
                )
            return value
        elif self.type == InputType.INT:
            try:
                return int(value)
            except ValueError:
                raise XPromptValidationError(
                    f"Argument '{self.name}' expects int, got '{value}'"
                ) from None
        elif self.type == InputType.FLOAT:
            try:
                return float(value)
            except ValueError:
                raise XPromptValidationError(
                    f"Argument '{self.name}' expects float, got '{value}'"
                ) from None
        elif self.type == InputType.BOOL:
            lower_value = value.lower()
            if lower_value in ("true", "1", "yes", "on"):
                return True
            elif lower_value in ("false", "0", "no", "off"):
                return False
            else:
                raise XPromptValidationError(
                    f"Argument '{self.name}' expects bool, got '{value}'"
                )
        elif self.type == InputType.ENUM:
            allowed = tuple(choice.value for choice in self.choices)
            if value not in allowed:
                raise XPromptValidationError(
                    f"Argument '{self.name}' expects one of "
                    f"{', '.join(allowed)}, got '{value}'"
                )
            return value
        elif self.type == InputType.CODE:
            from sase.xprompt.code_value import make_code_value

            return make_code_value(value, "bash")
        else:
            # Should never happen, but handle gracefully
            return value


@dataclass
class XPrompt:
    """An XPrompt template with optional typed input arguments.

    Attributes:
        name: The xprompt name (used in #name syntax).  Skills carry their
            namespaced reference name here (``skill/foo``, ``app/skill/foo``).
        content: The template content (may contain Jinja2 or legacy placeholders).
        inputs: List of input argument definitions from YAML front matter.
        source_path: File path or "config" indicating where this xprompt was loaded from.
        skill_name: The provider-visible skill name (``foo``) for definitions
            loaded from a canonical skill source, and ``None`` for every
            ordinary xprompt.  Never derive this by splitting :attr:`name`.
    """

    name: str
    content: str
    inputs: list[InputArg] = field(default_factory=list)
    source_path: str | None = None
    tags: frozenset[XPromptTag] = field(default_factory=frozenset)
    snippet: str | bool | None = None
    description: str | None = None
    skill: bool | list[str] | None = None
    skill_name: str | None = None
    log_skill_use: bool = True
    local_xprompts: dict[str, XPrompt] = field(default_factory=dict)
    memory_type: MemoryType | None = None
    discovery_rank: int | None = None

    def has_tag(self, tag: XPromptTag) -> bool:
        """Check if this xprompt has the given tag."""
        return tag in self.tags

    def get_input_by_name(self, name: str) -> InputArg | None:
        """Get an input argument definition by name.

        Args:
            name: The argument name to look up.

        Returns:
            The InputArg if found, None otherwise.
        """
        for input_arg in self.inputs:
            if input_arg.name == name:
                return input_arg
        return None

    def get_input_by_position(self, position: int) -> InputArg | None:
        """Get an input argument definition by position (0-indexed).

        Args:
            position: The 0-indexed position of the argument.

        Returns:
            The InputArg if position is valid, None otherwise.
        """
        if 0 <= position < len(self.inputs):
            return self.inputs[position]
        return None


def xprompt_to_workflow(xprompt: XPrompt) -> Workflow:
    """Convert an XPrompt to a Workflow with a single prompt_part step.

    This enables uniform handling of xprompts and workflows - all xprompts
    can be treated as workflows with a single prompt_part step.

    Args:
        xprompt: The XPrompt to convert.

    Returns:
        A Workflow object with a single prompt_part step containing the xprompt content.
    """
    from sase.xprompt.workflow_models import Workflow, WorkflowStep

    return Workflow(
        name=xprompt.name,
        inputs=xprompt.inputs,
        steps=[
            WorkflowStep(
                name="main",
                prompt_part=xprompt.content,
            )
        ],
        source_path=xprompt.source_path,
        tags=xprompt.tags,
        description=xprompt.description,
        xprompts=xprompt.local_xprompts,
        skill_name=xprompt.skill_name,
        memory_type=xprompt.memory_type,
        discovery_rank=xprompt.discovery_rank,
    )


def create_anonymous_workflow(query: str) -> Workflow:
    """Create an anonymous workflow for a raw query string.

    This allows raw queries (like "sase run 'hello'") to be treated
    as workflows with a single prompt step routed through WorkflowExecutor.

    Args:
        query: The raw query string.

    Returns:
        A Workflow object with a single prompt step containing the query.
    """
    from sase.core.time import generate_timestamp
    from sase.xprompt.workflow_models import Workflow, WorkflowStep

    name = f"tmp_{generate_timestamp()}"
    return Workflow(
        name=name,
        inputs=[],
        steps=[
            WorkflowStep(
                name="main",
                agent=query,  # Note: agent, not prompt_part
            )
        ],
        source_path=None,
        is_anonymous_workflow=True,
    )
