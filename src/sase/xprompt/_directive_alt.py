"""``%alt(...)`` / ``%(...)`` splitting and multi-model fan-out.

This module owns the logic that turns a single prompt with multiple
``%model`` directives or explicit ``%alt(a,b,...)`` calls into a list of
sub-prompts — one per Cartesian product entry — and the naming logic
that disambiguates spawned agents per runtime.
"""

from __future__ import annotations

import itertools
import re
from typing import TYPE_CHECKING

from ._directive_types import _DIRECTIVE_ALIASES, _DIRECTIVE_PATTERN
from ._disabled_regions import (
    protect_disabled_regions,
    unprotect_disabled_regions,
)
from ._exceptions import DirectiveError
from ._fenced_blocks import protect_fenced_blocks, unprotect_fenced_blocks
from ._parsing import find_matching_paren_for_args, parse_args

if TYPE_CHECKING:
    from .models import XPrompt

# Pattern to match %alt( or %( at a directive-valid position.
_ALT_DIRECTIVE_RE = re.compile(
    r"(?:^|(?<=\s)|(?<=[(\[{\"']))"
    r"(%(?:alt)?)\(",
    re.MULTILINE,
)


def has_alt_directive(prompt: str) -> bool:
    """Quick check whether a prompt contains a ``%alt(`` or ``%(`` directive.

    This avoids the overhead of full splitting and is suitable for
    early detection in the CLI auto-daemon routing.
    """
    if "%" not in prompt:
        return False
    return bool(re.search(r"(?:^|\s)%(?:alt)?\(", prompt, re.MULTILINE))


def split_prompt_for_alternatives(prompt: str) -> list[str] | None:
    """Split a prompt containing ``%alt(...)`` or ``%(...)`` into per-alternative prompts.

    Each argument becomes a separate prompt with the directive span replaced
    by that argument's text.  Arguments can be arbitrary text — directives,
    xprompt references, plain instructions, or ``[[text blocks]]``.

    ``%(...)`` is syntactic sugar for ``%alt(...)``.

    When multiple ``%alt``/``%(`` directives appear, a Cartesian product of
    all argument lists is computed — e.g. two directives with 2 and 3
    arguments produce 2 × 3 = 6 prompts.

    Returns ``None`` if there are no ``%alt``/``%(`` directives or all have
    zero arguments.  A single-arg ``%alt(foo)`` / ``%(foo)`` is treated as
    having an implicit empty variant, producing two alternatives for that
    directive.

    Raises:
        DirectiveError: If an opening parenthesis has no matching close.
    """
    matches = list(_ALT_DIRECTIVE_RE.finditer(prompt))
    if not matches:
        return None

    # Collect directive spans and their argument lists.
    directives: list[tuple[int, int, list[str]]] = []
    for match in matches:
        paren_start = match.end() - 1  # position of '('
        paren_end = find_matching_paren_for_args(prompt, paren_start)
        if paren_end is None:
            raise DirectiveError(
                "Unclosed '%alt('/'%(' directive — missing closing ')'"
            )

        inner = prompt[paren_start + 1 : paren_end]
        positional_args, _ = parse_args(inner)

        if len(positional_args) == 0:
            continue

        # Single arg: treat as "with/without" — append an implicit empty variant.
        if len(positional_args) == 1:
            positional_args.append("")

        directives.append((match.start(1), paren_end + 1, positional_args))

    if not directives:
        return None

    # Compute Cartesian product of all argument lists.
    all_arg_lists = [d[2] for d in directives]
    result: list[str] = []
    for combination in itertools.product(*all_arg_lists):
        # Replace spans right-to-left so earlier positions aren't shifted.
        replaced = prompt
        for (span_start, span_end, _), arg in reversed(
            list(zip(directives, combination, strict=True))
        ):
            replaced = replaced[:span_start] + arg + replaced[span_end:]
        result.append(replaced)
    return result


def split_prompt_for_models(
    prompt: str,
    *,
    extra_xprompts: dict[str, XPrompt] | None = None,
) -> list[str] | None:
    """Split a prompt with multi-model or ``%alt``/``%(`` directives into per-variant prompts.

    Handles three cases:

    1. ``%model(a,b,...)`` / ``%m(a,b,...)`` — rewritten internally to
       ``%alt(%model:a,%model:b,...)`` then split.
    2. Repeated scalar ``%model`` / ``%m`` directives (e.g.
       ``%model:opus\\n%model:sonnet``) — collected, deduped in document
       order, and collapsed into a single ``%alt(%model:a,%model:b,...)``
       before splitting.  Mixing scalar and paren forms is supported.
    3. Direct ``%alt(...)`` or ``%(...)`` usage — split as-is.

    Multiple model directives that all resolve to the same model yield a
    single variant (no split); duplicate ``%model`` directives inside
    fenced code blocks or ``%xprompts_enabled:false`` regions are ignored.

    Returns ``None`` if there is nothing to split (single unique model,
    single alt argument, or no splitting directive at all).  When only one
    unique model remains but multiple ``%model`` directives exist, the
    duplicates are tolerated downstream by :func:`extract_prompt_directives`
    (last-wins).
    """
    if "%" not in prompt:
        return None

    # Protect fenced code blocks and disabled regions so %model directives
    # inside them are neither collected nor rewritten.
    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced_blocks)
    disabled_regions: list[str] = []
    protected = protect_disabled_regions(protected, disabled_regions)

    # Identify inner regions of %alt(...) / %(...) so %model matches
    # nested inside them are not double-collected (they're handled by
    # split_prompt_for_alternatives).
    alt_inner_regions: list[tuple[int, int]] = []
    for alt_match in _ALT_DIRECTIVE_RE.finditer(protected):
        paren_start = alt_match.end() - 1
        paren_end = find_matching_paren_for_args(protected, paren_start)
        if paren_end is None:
            continue
        alt_inner_regions.append((paren_start + 1, paren_end))

    def _is_inside_alt(pos: int) -> bool:
        return any(start <= pos < end for start, end in alt_inner_regions)

    # Walk all directive matches and pick out %model / %m occurrences.
    directive_spans: list[tuple[int, int, list[str]]] = []
    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        raw_name = match.group(1)
        resolved = _DIRECTIVE_ALIASES.get(raw_name, raw_name)
        if resolved != "model":
            continue
        if _is_inside_alt(match.start()):
            continue

        has_open_paren = match.group(2) is not None
        colon_arg = match.group(3)
        plus_suffix = match.group(4)

        match_end = match.end()
        args: list[str] = []

        if has_open_paren:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(protected, paren_start)
            if paren_end is not None:
                paren_content = protected[paren_start + 1 : paren_end]
                positional_args, _ = parse_args(paren_content)
                args = [a for a in positional_args if a]
                match_end = paren_end + 1
        elif colon_arg is not None:
            if colon_arg.startswith("`") and colon_arg.endswith("`"):
                value = colon_arg[1:-1]
            else:
                value = colon_arg
            if value:
                args = [value]
        elif plus_suffix is not None:
            # %model+ is a plus-syntax sentinel with no real model value —
            # leave it alone for the extractor to handle.
            continue
        # Bare %model (no arg) contributes no model but its span is still
        # eligible for rewrite so the prompt stays clean.

        directive_spans.append((match.start(), match_end, args))

    if not directive_spans:
        # No collectable %model directives — fall through to alt-only handling
        # on the original (unprotected) prompt.
        sub_prompts = split_prompt_for_alternatives(prompt)
        if sub_prompts is None:
            return None
        return _apply_multi_model_naming(sub_prompts, extra_xprompts=extra_xprompts)

    # Dedupe model args in document order (first occurrence wins).
    seen_models: set[str] = set()
    unique_models: list[str] = []
    for _, _, args in directive_spans:
        for arg in args:
            model_key = _model_value_for_naming(arg, extra_xprompts=extra_xprompts)
            if model_key not in seen_models:
                seen_models.add(model_key)
                unique_models.append(arg)

    if len(unique_models) <= 1:
        # Zero or one unique model — no split needed.  Any duplicate scalar
        # %model directives are tolerated by extract_prompt_directives.
        sub_prompts = split_prompt_for_alternatives(prompt)
        if sub_prompts is None:
            return None
        return _apply_multi_model_naming(sub_prompts, extra_xprompts=extra_xprompts)

    # Two or more unique models — collapse every collected span into a
    # single %alt(%model:a,%model:b,...) directive at the first span's
    # position and remove the others.
    alt_args = ",".join(f"%model:{m}" for m in unique_models)
    replacement = f"%alt({alt_args})"

    # Absorb a trailing newline for non-first spans that occupy a whole
    # line, so the rewrite does not leave behind blank lines.
    adjusted: list[tuple[int, int, bool]] = []
    for i, (span_start, span_end, _) in enumerate(directive_spans):
        is_first = i == 0
        if (
            not is_first
            and span_end < len(protected)
            and protected[span_end] == "\n"
            and (span_start == 0 or protected[span_start - 1] == "\n")
        ):
            span_end += 1
        adjusted.append((span_start, span_end, is_first))

    # Splice right-to-left so earlier positions aren't shifted.
    rewritten = protected
    for span_start, span_end, is_first in reversed(adjusted):
        if is_first:
            rewritten = rewritten[:span_start] + replacement + rewritten[span_end:]
        else:
            rewritten = rewritten[:span_start] + rewritten[span_end:]

    rewritten = unprotect_disabled_regions(rewritten, disabled_regions)
    rewritten = unprotect_fenced_blocks(rewritten, fenced_blocks)

    sub_prompts = split_prompt_for_alternatives(rewritten)
    if sub_prompts is None:
        return None
    return _apply_multi_model_naming(sub_prompts, extra_xprompts=extra_xprompts)


def _extract_first_model_value(prompt: str) -> str | None:
    """Return the value of the first ``%model`` / ``%m`` directive in *prompt*.

    Used to identify the model bound to each sub-prompt produced by alt
    splitting.  Returns ``None`` if no directive is present, ignores
    fenced/disabled regions, and returns the empty string for a bare
    directive.
    """
    if "%" not in prompt:
        return None

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        raw_name = match.group(1)
        resolved = _DIRECTIVE_ALIASES.get(raw_name, raw_name)
        if resolved != "model":
            continue
        if match.group(2) is not None:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(protected, paren_start)
            if paren_end is None:
                return None
            inner = protected[paren_start + 1 : paren_end]
            args, _ = parse_args(inner)
            return args[0] if args else None
        colon_arg = match.group(3)
        if colon_arg is not None:
            if colon_arg.startswith("`") and colon_arg.endswith("`"):
                return colon_arg[1:-1]
            return colon_arg
        return None
    return None


def _extract_and_strip_name_directive(
    prompt: str,
) -> tuple[str, str | None, bool]:
    """Strip the first ``%name`` / ``%n`` directive from *prompt*.

    Returns ``(prompt_without_name, raw_value, was_bare)``.  ``raw_value``
    is ``None`` if no directive existed, an empty string if the directive
    was bare; ``was_bare`` is ``True`` only in the latter case.
    Trailing newline is absorbed when the directive owns its line.
    """
    if "%" not in prompt:
        return prompt, None, False

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    raw_value: str | None = None
    span: tuple[int, int] | None = None

    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        raw_name = match.group(1)
        resolved = _DIRECTIVE_ALIASES.get(raw_name, raw_name)
        if resolved != "name":
            continue

        match_end = match.end()
        if match.group(2) is not None:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(protected, paren_start)
            if paren_end is not None:
                inner = protected[paren_start + 1 : paren_end]
                args, _ = parse_args(inner)
                raw_value = args[0] if args else ""
                match_end = paren_end + 1
            else:
                raw_value = ""
        elif match.group(3) is not None:
            colon_arg = match.group(3)
            if colon_arg.startswith("`") and colon_arg.endswith("`"):
                raw_value = colon_arg[1:-1]
            else:
                raw_value = colon_arg
        else:
            raw_value = ""

        span_start, span_end = match.start(), match_end
        if (
            span_end < len(protected)
            and protected[span_end] == "\n"
            and (span_start == 0 or protected[span_start - 1] == "\n")
        ):
            span_end += 1
        span = (span_start, span_end)
        break

    if span is None:
        result = unprotect_disabled_regions(protected, disabled)
        return unprotect_fenced_blocks(result, fenced), None, False

    s, e = span
    stripped = protected[:s] + protected[e:]
    stripped = unprotect_disabled_regions(stripped, disabled)
    stripped = unprotect_fenced_blocks(stripped, fenced)
    return stripped, raw_value, not raw_value


def _runtime_label_for_model(model: str) -> str:
    """Map a model string to its runtime/provider label (e.g. ``"claude"``).

    Falls back to the configured default provider if the model is unknown
    — mirrors the resolution used in ``run_agent_phases.py``.
    """
    from sase.llm_provider.registry import (
        get_default_provider_name,
        provider_short_name_map,
        resolve_model_provider,
    )

    provider, _ = resolve_model_provider(model)
    name = provider or get_default_provider_name()
    return provider_short_name_map().get(name, name)


def _model_value_for_naming(
    model: str,
    *,
    extra_xprompts: dict[str, XPrompt] | None = None,
) -> str:
    """Resolve xprompt shorthand in a model token for naming only."""
    if "#" not in model:
        return model

    from .processor import process_xprompt_references

    expanded = process_xprompt_references(
        model,
        extra_xprompts=extra_xprompts or None,
    ).strip()
    if expanded == model:
        return model
    return expanded


def _model_disambiguator_for_naming(raw_model: str, label_model: str) -> str:
    """Return the model text used after ``<runtime>-`` in agent names."""
    if raw_model.startswith("#") and label_model == raw_model:
        return raw_model[1:]
    return label_model


def _inject_name_directive(prompt: str, name: str) -> str:
    """Prepend a ``%name:<name>`` line to *prompt*."""
    return f"%name:{name}\n{prompt}"


def _apply_multi_model_naming(
    sub_prompts: list[str],
    *,
    extra_xprompts: dict[str, XPrompt] | None = None,
) -> list[str]:
    """Add ``%name:<base>.<runtime>`` to each sub-prompt of a multi-model fan-out.

    Triggers only when the sub-prompts span at least two distinct ``%model``
    values.  The base name is taken from the first ``%name`` directive found
    across the sub-prompts; if none, an auto name is generated once and
    shared.  Same-runtime collisions disambiguate with the model suffix
    (``foo.claude-opus`` / ``foo.claude-sonnet``).
    """
    models_per_sub = [_extract_first_model_value(s) for s in sub_prompts]
    label_models_per_sub = [
        _model_value_for_naming(model, extra_xprompts=extra_xprompts)
        if model is not None
        else None
        for model in models_per_sub
    ]
    distinct_label_models = [m for m in dict.fromkeys(label_models_per_sub) if m]
    if len(distinct_label_models) < 2:
        return sub_prompts

    base: str | None = None
    for sub in sub_prompts:
        _, value, _ = _extract_and_strip_name_directive(sub)
        if value:
            base = value
            break
    if not base:
        from sase.agent.names import get_next_auto_name

        base = get_next_auto_name()

    from sase.llm_provider.registry import model_short_alias_map

    aliases = model_short_alias_map()
    runtime_for = {m: _runtime_label_for_model(m) for m in distinct_label_models}
    runtime_count: dict[str, int] = {}
    for r in runtime_for.values():
        runtime_count[r] = runtime_count.get(r, 0) + 1
    suffix_for: dict[str, str] = {}
    raw_for_label = {
        label: raw
        for raw, label in zip(models_per_sub, label_models_per_sub, strict=True)
        if raw is not None and label is not None
    }
    for m in distinct_label_models:
        r = runtime_for[m]
        if runtime_count[r] > 1:
            short = aliases.get(m, _model_disambiguator_for_naming(raw_for_label[m], m))
            suffix_for[m] = f"{r}-{short}"
        else:
            suffix_for[m] = r
    # Aliases can collide (two distinct models mapped to the same short
    # form); fall back to raw model names for the colliding runtime so
    # spawned agent names stay distinct.
    if len(set(suffix_for.values())) != len(suffix_for):
        for m in distinct_label_models:
            r = runtime_for[m]
            if runtime_count[r] > 1:
                suffix_for[m] = (
                    f"{r}-{_model_disambiguator_for_naming(raw_for_label[m], m)}"
                )

    out: list[str] = []
    for sub, label_model in zip(sub_prompts, label_models_per_sub, strict=True):
        if label_model is None or label_model not in suffix_for:
            out.append(sub)
            continue
        stripped, _, _ = _extract_and_strip_name_directive(sub)
        out.append(
            _inject_name_directive(stripped, f"{base}.{suffix_for[label_model]}")
        )
    return out
