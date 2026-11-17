"""Source-aware Jinja rendering for prompt preprocessing.

Renders a source template with the original typed context values (so Jinja
conditionals, indexing, filters, and loops see real data) while executing
only literal ``$(command)`` expressions from authorized source text.
Interpolated values are data regardless of their content: each ``{{ }}``
output is wrapped in a guard token before any command planning runs, so
generated text can never reach an execution pass and a command assembled
across an interpolation boundary stays literal.

Only template text that Jinja actually evaluates can execute: a command in
a false ``{% if %}`` branch never renders and is never planned. Fenced code
blocks and disabled regions keep their literal-zone rules.
"""

from __future__ import annotations

from typing import Any

from jinja2 import Environment

from sase.macro._disabled_regions import protect_disabled_regions
from sase.macro._disabled_regions import unprotect_disabled_regions
from sase.macro._fenced_blocks import protect_fenced_blocks, unprotect_fenced_blocks
from sase.macro.cmdsub_source import (
    CmdsubProvenance,
    GeneratedTextGuard,
    execute_eligible_commands,
)


def _marking_env(
    guard: GeneratedTextGuard,
    base: Environment,
) -> Environment:
    """Build a prompt Jinja environment that marks interpolations.

    The environment mirrors *base* (undefined handling, filters, tests)
    but its ``finalize`` wraps every ``{{ }}`` output in markers embedding
    the guard nonce, so rendered data can never be confused with source
    text. ``finalize`` only touches ``{{ }}`` outputs: ``{% set %}``
    bindings and ``{% if %}``/``{% for %}`` tests keep seeing the original
    typed values. Nested output markers are flattened by ``guard.mark``;
    hiding the rendered spans rejects unbalanced markers rather than leaking
    them into downstream prompt processing.
    """
    base_finalize = base.finalize

    def _marking_finalize(value: Any) -> str:
        finalized = base_finalize(value) if base_finalize is not None else value
        return guard.mark(finalized)

    env = Environment(undefined=base.undefined, finalize=_marking_finalize)
    env.filters.update(base.filters)
    env.tests.update(base.tests)
    return env


def render_source_template(
    template: str,
    context: dict[str, Any],
    *,
    provenance: CmdsubProvenance,
    guard: GeneratedTextGuard,
) -> str:
    """Render *template* with source-aware command substitution.

    Args:
        template: The authored source template.
        context: Jinja2 template context dict. Values are data even when
            they contain ``$(...)`` or macro syntax.
        provenance: Explicit boundary provenance. Generated text and agent
            launches render without executing anything.
        guard: Guard that receives one token per interpolated value and per
            command-stdout splice. The returned text still contains those
            tokens; the caller unwraps them once downstream passes no
            longer need generated text hidden.

    Returns:
        The rendered text with guard tokens in place of generated spans.
    """
    from sase.macro._jinja import get_global_template_vars
    from sase.macro.workflow_executor_utils import create_jinja_env

    base = create_jinja_env()
    env = _marking_env(guard, base)

    fenced_blocks: list[str] = []
    protected_template = protect_fenced_blocks(template, fenced_blocks)
    disabled_regions: list[str] = []
    protected_template = protect_disabled_regions(protected_template, disabled_regions)

    merged = {**get_global_template_vars(), **context}
    jinja_template = env.from_string(protected_template)
    rendered = jinja_template.render(merged)

    rendered = unprotect_disabled_regions(rendered, disabled_regions)
    rendered = unprotect_fenced_blocks(rendered, fenced_blocks)

    tokenized = guard.hide_marked_spans(rendered)

    return execute_eligible_commands(tokenized, provenance=provenance, guard=guard)
