"""Jinja AST protection for source-aware command substitution.

Wraps final-emission interpolation outputs with ``__protect`` so emitted
data is marked for later hiding while capture buffers stay clean for Jinja
computation. Imported lazily (use-site) by macro rendering so TUI first
paint never pulls the AST transformer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jinja2 import nodes

if TYPE_CHECKING:
    from sase.macro.cmdsub_source import GeneratedTextGuard

_CAPTURE_NODE_TYPES = (
    nodes.AssignBlock,
    nodes.Macro,
    nodes.CallBlock,
    nodes.FilterBlock,
)


def transform_protect_final_outputs(
    template_ast: nodes.Template, protect_name: str = "__protect"
) -> nodes.Template:
    """Wrap final-emission Jinja interpolation outputs with ``__protect``.

    Outputs inside capture buffers (``{% set %}`` blocks, macro bodies,
    caller blocks, filter blocks) stay clean so Jinja comparisons, length,
    indexing, slicing, filters, and caller tests operate on real values.
    Only interpolation outputs (non-TemplateData) emitted to the final
    buffer are wrapped, so emitted data is marked for later hiding while
    computation strings stay clean. Pure TemplateData outputs are authored
    source literals and stay executable when their branch is taken. Final
    filter blocks containing interpolations get ``__protect`` appended as
    their last filter. Call blocks in final position are left unprotected
    (their bodies stay clean for caller semantics); their results contain
    no markers, so marker-leak checks still pass.
    """

    def _is_protect_call(node: nodes.Node) -> bool:
        return (
            isinstance(node, nodes.Call)
            and isinstance(node.node, nodes.Name)
            and node.node.name == protect_name
        )

    def _contains_interpolation(root: nodes.Node) -> bool:
        """Whether *root* contains a non-literal interpolation output."""
        found = False

        def _scan(node: nodes.Node) -> None:
            nonlocal found
            if found:
                return
            if isinstance(node, nodes.Output):
                for value in node.nodes:  # type: ignore[attr-defined]
                    if not isinstance(value, nodes.TemplateData):
                        found = True
                        return
            for _field, value in node.iter_fields():
                if isinstance(value, nodes.Node):
                    _scan(value)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, nodes.Node):
                            _scan(item)

        _scan(root)
        return found

    def _walk(node: nodes.Node, in_capture: bool) -> None:
        child_in_capture = in_capture or isinstance(node, _CAPTURE_NODE_TYPES)
        if isinstance(node, nodes.Output) and not in_capture:
            wrapped: list[nodes.Node] = []
            changed = False
            for value in node.nodes:  # type: ignore[attr-defined]
                if isinstance(value, nodes.TemplateData):
                    wrapped.append(value)
                elif _is_protect_call(value):
                    wrapped.append(value)
                else:
                    wrapped.append(
                        nodes.Call(
                            nodes.Name(protect_name, "load"),
                            [value],
                            [],
                            None,
                            None,
                        )
                    )
                    changed = True
            if changed:
                node.nodes = wrapped  # type: ignore[assignment]
        if isinstance(node, nodes.FilterBlock) and not in_capture:
            if _contains_interpolation(node):
                filt = node.filter  # type: ignore[attr-defined]
                node.filter = nodes.Filter(  # type: ignore[arg-type]
                    filt, protect_name, [], [], None, None
                )
        for _field, value in node.iter_fields():
            if isinstance(value, nodes.Node):
                _walk(value, child_in_capture)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, nodes.Node):
                        _walk(item, child_in_capture)

    _walk(template_ast, False)
    return template_ast


def render_with_guard(
    content: str,
    context: dict[str, Any],
    macro_name: str,
    guard: GeneratedTextGuard,
) -> str:
    """Render macro content with source-aware data protection.

    Builds a marking Jinja environment (preserving prompt filters), wraps
    final-emission interpolations with ``__protect`` via AST transformation
    (captures stay clean for value semantics), renders, and hides marked
    spans behind guard tokens. Raises ``MacroArgumentError`` on template
    errors and ``GeneratedTextLeakError``-derived ``MacroArgumentError`` on
    marker residue.
    """
    from jinja2 import BaseLoader, Environment, StrictUndefined, TemplateError

    from sase.macro._jinja import register_prompt_filters
    from sase.macro._exceptions import MacroArgumentError
    from sase.macro.cmdsub_source import GeneratedTextLeakError

    def __protect(value: Any) -> str:
        return guard.mark(value)

    marking_env = Environment(
        loader=BaseLoader(),
        undefined=StrictUndefined,
        autoescape=False,
    )
    register_prompt_filters(marking_env)
    marking_env.filters["__protect"] = lambda value: guard.mark(value)
    context = dict(context)
    context["__protect"] = __protect

    try:
        template_ast = marking_env.parse(content)
        transform_protect_final_outputs(template_ast)
        code = marking_env.compile(template_ast)
        template = marking_env.template_class.from_code(
            marking_env, code, marking_env.globals
        )
        rendered = template.render(**context)
    except TemplateError as e:
        raise MacroArgumentError(f"Macro '#{macro_name}' template error: {e}") from e
    try:
        return guard.hide_marked_spans(rendered)
    except GeneratedTextLeakError as e:
        raise MacroArgumentError(f"Macro '#{macro_name}' template error: {e}") from e
