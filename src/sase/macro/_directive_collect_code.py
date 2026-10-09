"""Code-directive (`%if` / `%proc`) collection for prompt directives."""

from __future__ import annotations

import re

from ._directive_collect_state import CollectedDirectives
from ._exceptions import DirectiveError
from ._parsing import find_matching_paren_for_args, parse_args

_PROC_OPTION_KEYS = frozenset(
    {"bash", "python", "timeout", "idle_timeout", "cwd", "workspace", "label"}
)
_PROC_BODY_KEYS = frozenset({"bash", "python"})


def collect_code_directive(
    collected: CollectedDirectives,
    prompt: str,
    match: re.Match[str],
    name: str,
) -> None:
    """Collect one `%if` / `%proc` directive into the shared state."""
    from sase.macro.code_value import (
        TYPED_LAUNCH_UNITS_DISABLED_MESSAGE,
        make_code_value,
        typed_launch_units_enabled,
    )

    has_open_paren = match.group(2) is not None
    colon_arg = match.group(3)
    plus_suffix = match.group(4)
    is_bare = not has_open_paren and colon_arg is None and plus_suffix is None
    if is_bare and not prompt.startswith("::", match.end()):
        return
    if not typed_launch_units_enabled():
        raise DirectiveError(TYPED_LAUNCH_UNITS_DISABLED_MESSAGE)
    if name == "if":
        raise DirectiveError(
            "%if requires %if:: followed by exactly one closed bash or python fence."
        )
    if plus_suffix is not None or (colon_arg is not None and not has_open_paren):
        raise DirectiveError(
            '%proc does not accept colon or plus forms; use %proc("cmd"), '
            "%proc(bash=...|python=...), or %proc:: plus a fence."
        )
    if not has_open_paren:
        raise DirectiveError(
            '%proc requires a body: %proc("cmd"), %proc(bash=...|python=...), '
            "or %proc:: plus a fence."
        )
    paren_start = match.end() - 1
    paren_end = find_matching_paren_for_args(prompt, paren_start)
    if paren_end is None:
        raise DirectiveError("Malformed %proc(...) directive: missing closing ')'.")
    paren_content = prompt[paren_start + 1 : paren_end]
    try:
        positional_args, named_args = parse_args(
            paren_content,
            reject_duplicate_named_args=True,
        )
    except ValueError as exc:
        raise DirectiveError(str(exc)) from exc
    unknown = sorted(key for key in named_args if key not in _PROC_OPTION_KEYS)
    if unknown:
        keys = ", ".join(f"{key}=" for key in unknown)
        raise DirectiveError(
            f"Unsupported keyword on %proc: {keys}. Only bash=, python=, "
            "timeout=, idle_timeout=, cwd=, workspace=, and label= are supported."
        )
    if "bash" in named_args and "python" in named_args:
        raise DirectiveError("%proc cannot combine bash= and python=.")
    positional_body = next((arg for arg in positional_args if arg), "")
    named_body_key = next(
        (key for key in ("bash", "python") if key in named_args), None
    )
    if positional_body and named_body_key is not None:
        raise DirectiveError(
            "%proc cannot combine a positional body with bash= or python=."
        )
    if positional_body:
        language = "bash"
        source = positional_body
    elif named_body_key is not None:
        language = named_body_key
        source = named_args[named_body_key]
    else:
        raise DirectiveError(
            '%proc requires a body: %proc("cmd"), %proc(bash=...|python=...), '
            "or %proc:: plus a fence."
        )
    if not source.strip():
        raise DirectiveError("%proc requires a non-empty body.")
    if collected.proc_code is not None:
        raise DirectiveError("Only one %proc is allowed per launch unit.")
    collected.proc_code = make_code_value(source, language)
    collected.proc_options = {
        key: value for key, value in named_args.items() if key not in _PROC_BODY_KEYS
    }
    collected.regions_to_remove.append((match.start(), paren_end + 1))
