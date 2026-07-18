"""Fan-out child naming for ``%alt`` / ``%model`` launch plans."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._directive_types import _DIRECTIVE_ALIASES, _DIRECTIVE_PATTERN
from ._disabled_regions import (
    protect_disabled_regions,
    unprotect_disabled_regions,
)
from ._fenced_blocks import protect_fenced_blocks, unprotect_fenced_blocks
from ._parsing import find_matching_paren_for_args, parse_args
from .effort import split_model_effort

if TYPE_CHECKING:
    from sase.core.agent_launch_wire import LaunchFanoutPlanWire, LaunchFanoutSlotWire

    from .models import XPrompt


@dataclass(frozen=True)
class _NamedFanoutPrompt:
    prompt: str
    name_generated: bool


def _strip_model_alias_prefix(value: str) -> str:
    from sase.llm_provider.config import strip_model_alias_prefix

    return strip_model_alias_prefix(value)


def _extract_first_model_value(prompt: str) -> str | None:
    """Return the value of the first ``%model`` / ``%m`` directive in *prompt*.

    Used to identify the model bound to each sub-prompt produced by alt
    splitting.  Returns ``None`` if no directive is present, ignores
    fenced/disabled regions, and returns the empty string for a bare
    directive. A trailing ``@<effort>`` suffix is stripped so the value names
    the clean model; backtick-literal values keep their ``@`` verbatim.
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
            if not args:
                return None
            clean_model, _ = split_model_effort(args[0])
            return _strip_model_alias_prefix(clean_model)
        colon_arg = match.group(3)
        if colon_arg is not None:
            if colon_arg.startswith("`") and colon_arg.endswith("`"):
                return colon_arg[1:-1]
            clean_model, _ = split_model_effort(colon_arg)
            return _strip_model_alias_prefix(clean_model)
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


def runtime_label_for_model(model: str) -> str:
    """Resolve through the compatibility facade so existing patches keep working."""
    from ._directive_alt import (
        runtime_label_for_model as facade_runtime_label_for_model,
    )

    return facade_runtime_label_for_model(model)


def _model_value_for_naming(
    model: str,
    *,
    extra_xprompts: dict[str, XPrompt] | None = None,
) -> str:
    """Resolve xprompt shorthand and configured aliases for naming only."""
    from sase.llm_provider.config import resolve_model_alias

    model = _strip_model_alias_prefix(model)
    if "#" not in model:
        return resolve_model_alias(model)

    from .processor import process_xprompt_references

    expanded = process_xprompt_references(
        model,
        extra_xprompts=extra_xprompts or None,
    ).strip()
    if expanded == model:
        return resolve_model_alias(model)
    return resolve_model_alias(expanded)


def _model_disambiguator_for_naming(raw_model: str, label_model: str) -> str:
    """Return the model text used after ``<runtime>-`` in agent names."""
    if raw_model.startswith("#") and label_model == raw_model:
        return raw_model[1:]
    return label_model


def _model_suffix_value(model: str) -> str:
    """Return the provider-local model value used for alias/fallback suffixes."""
    from sase.llm_provider.registry import resolve_model_provider

    _, resolved_model = resolve_model_provider(_strip_model_alias_prefix(model))
    return resolved_model


def _inject_name_directive(prompt: str, name: str) -> str:
    """Prepend a ``%name:<name>`` line to *prompt*."""
    return f"%name:{name}\n{prompt}"


def apply_fanout_naming(
    plan: LaunchFanoutPlanWire,
    *,
    extra_xprompts: dict[str, XPrompt] | None = None,
) -> list[str]:
    """Compatibility wrapper returning only per-slot fan-out prompt text."""
    return [
        named.prompt
        for named in apply_fanout_naming_with_metadata(
            plan,
            extra_xprompts=extra_xprompts,
        )
    ]


def apply_fanout_naming_with_metadata(
    plan: LaunchFanoutPlanWire,
    *,
    extra_xprompts: dict[str, XPrompt] | None = None,
) -> list[_NamedFanoutPrompt]:
    """Add ``%name:<base>.<id>`` to each named child of a fan-out plan.

    The base name is taken from the first explicit ``%name`` directive found
    across the slots; if none, a resume-derived or auto name is generated once
    and shared.  Multi-model fan-outs preserve the existing runtime/model
    suffixes unless a named ``%alt`` branch supplies the slot identity.
    """
    slots = list(plan.slots)
    sub_prompts = [slot.prompt for slot in slots]
    models_per_sub = [_slot_model_value(slot) for slot in slots]
    label_models_per_sub = [
        _model_value_for_naming(model, extra_xprompts=extra_xprompts)
        if model is not None
        else None
        for model in models_per_sub
    ]
    distinct_label_models = [m for m in dict.fromkeys(label_models_per_sub) if m]
    suffixes = _fanout_suffixes(
        slots,
        models_per_sub=models_per_sub,
        label_models_per_sub=label_models_per_sub,
        distinct_label_models=distinct_label_models,
    )
    if all(suffix is None for suffix in suffixes):
        return [
            _NamedFanoutPrompt(prompt=sub, name_generated=False) for sub in sub_prompts
        ]

    base: str | None = None
    for sub in sub_prompts:
        _, value, was_bare = _extract_and_strip_name_directive(sub)
        if value and not was_bare:
            base = value
            break

    name_generated = base is None
    if not base:
        from sase.agent.names import (
            agent_name_allocation_lock,
            allocate_resume_name,
            allocate_wait_name,
            single_wait_agent_name,
            sole_resume_agent_name,
        )

        resume_target = sole_resume_agent_name(sub_prompts[0])
        wait_target = None if resume_target else single_wait_agent_name(sub_prompts[0])
        if wait_target is not None:
            from sase.core.agent_tribe import parse_tribe_reference

            if parse_tribe_reference(wait_target) is not None:
                wait_target = None
        if resume_target or wait_target:
            with agent_name_allocation_lock():
                if resume_target:
                    base = allocate_resume_name(resume_target)
                else:
                    assert wait_target is not None
                    base = allocate_wait_name(wait_target)
        else:
            # No explicit, resume-derived, or wait-derived base exists. Treat
            # the generated base as the generic auto-name template; parent-side
            # launch planning will allocate the concrete token, and grouped
            # fan-out slots can share that token atomically.
            base = "@"

    out: list[_NamedFanoutPrompt] = []
    for sub, suffix in zip(sub_prompts, suffixes, strict=True):
        if suffix is None:
            out.append(_NamedFanoutPrompt(prompt=sub, name_generated=False))
            continue
        stripped, _, _ = _extract_and_strip_name_directive(sub)
        out.append(
            _NamedFanoutPrompt(
                prompt=_inject_name_directive(stripped, f"{base}.{suffix}"),
                name_generated=name_generated,
            )
        )
    return out


def _slot_model_value(slot: LaunchFanoutSlotWire) -> str | None:
    if slot.model is not None:
        return _strip_model_alias_prefix(slot.model)
    return _extract_first_model_value(slot.prompt)


def _fanout_suffixes(
    slots: list[LaunchFanoutSlotWire],
    *,
    models_per_sub: list[str | None],
    label_models_per_sub: list[str | None],
    distinct_label_models: list[str],
) -> list[str | None]:
    model_suffix_for = _model_suffixes(
        models_per_sub=models_per_sub,
        label_models_per_sub=label_models_per_sub,
        distinct_label_models=distinct_label_models,
    )
    component_lists = [slot.alt_id.split(".") if slot.alt_id else [] for slot in slots]
    model_axis = _detect_model_axis(component_lists, label_models_per_sub)

    suffixes: list[str | None] = []
    for slot, label_model, components in zip(
        slots,
        label_models_per_sub,
        component_lists,
        strict=True,
    ):
        alt_suffix = _safe_fanout_suffix(slot.alt_id)
        if (
            label_model is not None
            and len(distinct_label_models) >= 2
            and label_model in model_suffix_for
        ):
            if _alt_id_has_named_component(slot.alt_id):
                suffixes.append(alt_suffix)
            elif model_axis is not None and model_axis < len(components):
                model_components = list(components)
                model_components[model_axis] = model_suffix_for[label_model]
                suffixes.append(_safe_fanout_suffix(".".join(model_components)))
            else:
                suffixes.append(alt_suffix)
        else:
            suffixes.append(alt_suffix)

    if _has_duplicate_suffixes(suffixes):
        suffixes = [_safe_fanout_suffix(slot.alt_id) for slot in slots]
    return suffixes


def _detect_model_axis(
    component_lists: list[list[str]],
    label_models_per_sub: list[str | None],
) -> int | None:
    max_component_count = max(
        (len(components) for components in component_lists), default=0
    )
    candidates: list[int] = []
    for index in range(max_component_count):
        component_models: dict[str, str | None] = {}
        valid = True
        for components, label_model in zip(
            component_lists,
            label_models_per_sub,
            strict=True,
        ):
            if index >= len(components) or not components[index]:
                valid = False
                break
            component = components[index]
            previous = component_models.setdefault(component, label_model)
            if previous != label_model:
                valid = False
                break
        if not valid:
            continue
        models = {model for model in component_models.values() if model is not None}
        if len(models) >= 2:
            candidates.append(index)
    if len(candidates) == 1:
        return candidates[0]
    return None


def _has_duplicate_suffixes(suffixes: list[str | None]) -> bool:
    concrete_suffixes = [suffix for suffix in suffixes if suffix is not None]
    return len(set(concrete_suffixes)) != len(concrete_suffixes)


def _model_suffixes(
    *,
    models_per_sub: list[str | None],
    label_models_per_sub: list[str | None],
    distinct_label_models: list[str],
) -> dict[str, str]:
    if len(distinct_label_models) < 2:
        return {}

    from sase.llm_provider.registry import model_short_alias_map

    aliases = model_short_alias_map()
    runtime_for = {m: runtime_label_for_model(m) for m in distinct_label_models}
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
            suffix_value = _model_suffix_value(m)
            short = aliases.get(m) or aliases.get(suffix_value)
            if short is None:
                short = _model_disambiguator_for_naming(
                    raw_for_label[m],
                    suffix_value,
                )
            suffix_for[m] = _safe_fanout_suffix(f"{r}-{short}") or r
        else:
            suffix_for[m] = r
    # Aliases can collide (two distinct models mapped to the same short
    # form); fall back to raw model names for the colliding runtime so
    # spawned agent names stay distinct.
    if len(set(suffix_for.values())) != len(suffix_for):
        for m in distinct_label_models:
            r = runtime_for[m]
            if runtime_count[r] > 1:
                suffix_value = _model_suffix_value(m)
                disambiguator = _model_disambiguator_for_naming(
                    raw_for_label[m],
                    suffix_value,
                )
                suffix_for[m] = _safe_fanout_suffix(f"{r}-{disambiguator}") or r
    return suffix_for


def _alt_id_has_named_component(alt_id: str | None) -> bool:
    if not alt_id:
        return False
    return any(not part.isdigit() for part in alt_id.split(".") if part)


def _safe_fanout_suffix(alt_id: str | None) -> str | None:
    if not alt_id:
        return None
    suffix = re.sub(r"[^A-Za-z0-9_.]+", "_", alt_id.strip().replace("-", "_"))
    suffix = re.sub(r"\.+", ".", suffix).strip("._-")
    return suffix or None
