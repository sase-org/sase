"""Suffix parsing utilities for Patch entries."""

from typing import NamedTuple


class ParsedSuffix(NamedTuple):
    """Result of parsing a suffix value."""

    value: str | None
    suffix_type: str | None


# Prefix mappings in priority order (longer prefixes first)
_PREFIX_MAP: list[tuple[str, str | None]] = [
    ("~!:", "rejected_proposal"),
    ("~@:", "killed_agent"),
    ("~$:", "killed_process"),
    ("?$:", "pending_dead_process"),
    ("!:", "error"),
    ("@:", "running_agent"),
    ("$:", "running_process"),
    ("%:", "summarize_complete"),
    ("^:", "metahook_complete"),
    ("~:", None),  # Legacy prefix, treated as plain suffix
]


def parse_suffix_prefix(suffix_val: str | None) -> ParsedSuffix:
    """Parse suffix prefix markers and return (value, suffix_type).

    Handles all suffix type markers:
    - "~!:" -> rejected_proposal
    - "!:" -> error
    - "~@:" -> killed_agent
    - "@:" -> running_agent
    - "@" (alone) -> running_agent with empty value
    - "~$:" -> killed_process
    - "?$:" -> pending_dead_process
    - "$:" -> running_process
    - "%:" -> summarize_complete
    - "%" (alone) -> summarize_complete with empty value
    - "^:" -> metahook_complete
    - "^" (alone) -> metahook_complete with empty value
    - "~:" -> plain (legacy, no suffix_type)

    Args:
        suffix_val: The raw suffix string to parse

    Returns:
        ParsedSuffix with value (message without prefix) and suffix_type.
    """
    if suffix_val is None:
        return ParsedSuffix(None, None)

    for prefix, suffix_type in _PREFIX_MAP:
        if suffix_val.startswith(prefix):
            # Special case: "!: metahook" or "!: metahook | ..." is metahook_complete
            if prefix == "!:":
                remainder = suffix_val[len(prefix) :].lstrip()
                if remainder == "metahook" or remainder.startswith("metahook |"):
                    # Extract content after "metahook | " if present
                    if remainder.startswith("metahook |"):
                        value = remainder[len("metahook |") :].strip()
                    else:
                        value = ""
                    return ParsedSuffix(value, "metahook_complete")
            return ParsedSuffix(suffix_val[len(prefix) :].strip(), suffix_type)

    # Handle standalone markers
    if suffix_val == "@":
        return ParsedSuffix("", "running_agent")
    if suffix_val == "%":
        return ParsedSuffix("", "summarize_complete")
    if suffix_val == "^":
        return ParsedSuffix("", "metahook_complete")

    # No prefix - return as-is with no suffix_type
    return ParsedSuffix(suffix_val, None)
