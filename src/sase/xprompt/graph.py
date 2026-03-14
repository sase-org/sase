"""Workflow DAG visualization as Mermaid or text."""

from __future__ import annotations

import re

from sase.xprompt.workflow_models import Workflow, WorkflowStep

# Match Jinja2 variable/expression blocks: {{ ... }}
_JINJA_EXPR_RE = re.compile(r"\{\{\s*(.+?)\s*\}\}")
# Leading identifier from an expression (e.g. "step_name" from "step_name.field | filter")
_IDENT_RE = re.compile(r"^([a-zA-Z_]\w*)")


def _get_step_texts(step: WorkflowStep) -> list[str]:
    """Collect all template strings from a step that may contain Jinja2 refs."""
    texts: list[str] = []
    for attr in ("agent", "bash", "python", "prompt_part", "condition"):
        val = getattr(step, attr, None)
        if val:
            texts.append(val)
    if step.for_loop:
        texts.extend(step.for_loop.values())
    if step.repeat_config:
        texts.append(step.repeat_config.condition)
    if step.while_config:
        texts.append(step.while_config.condition)
    return texts


def extract_step_references(step: WorkflowStep, all_step_names: set[str]) -> set[str]:
    """Parse Jinja2 expressions in *step* and return referenced step names.

    Only returns names that exist in *all_step_names* and differ from the step
    itself (self-references in repeat/while loops are excluded).
    """
    refs: set[str] = set()
    for text in _get_step_texts(step):
        for match in _JINJA_EXPR_RE.finditer(text):
            ident_match = _IDENT_RE.match(match.group(1))
            if ident_match:
                name = ident_match.group(1)
                if name in all_step_names and name != step.name:
                    refs.add(name)
    if step.parallel_config:
        for sub in step.parallel_config.steps:
            refs.update(extract_step_references(sub, all_step_names))
    return refs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def step_type(step: WorkflowStep) -> str:
    if step.agent is not None:
        return "agent"
    if step.bash is not None:
        return "bash"
    if step.python is not None:
        return "python"
    if step.prompt_part is not None:
        return "prompt_part"
    if step.parallel_config is not None:
        return "parallel"
    return "unknown"


def _mermaid_id(name: str) -> str:
    """Produce a Mermaid-safe node identifier."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


def _escape_label(text: str) -> str:
    """Escape a string for use inside a Mermaid quoted label."""
    return text.replace('"', "&quot;")


def control_annotations(step: WorkflowStep) -> str:
    """Short control-flow annotation string for node labels."""
    parts: list[str] = []
    if step.condition:
        parts.append("if:")
    if step.for_loop:
        parts.append("for:")
    if step.repeat_config:
        parts.append("repeat:")
    if step.while_config:
        parts.append("while:")
    return " ".join(parts)


def _node_label(step: WorkflowStep) -> str:
    """Build the display label for a step node."""
    stype = step_type(step)
    flow = control_annotations(step)
    second = stype if not flow else f"{stype} {flow}"
    return _escape_label(f"{step.name}<br/>{second}")


def collect_all_step_names(steps: list[WorkflowStep]) -> set[str]:
    """Gather names of all steps including parallel sub-steps."""
    names: set[str] = set()
    for step in steps:
        names.add(step.name)
        if step.parallel_config:
            for sub in step.parallel_config.steps:
                names.add(sub.name)
    return names


# ---------------------------------------------------------------------------
# Mermaid generation
# ---------------------------------------------------------------------------


def _emit_leaf(step: WorkflowStep, lines: list[str], indent: int = 4) -> None:
    """Emit a single (non-parallel) Mermaid node."""
    pad = " " * indent
    sid = _mermaid_id(step.name)
    label = _node_label(step)
    stype = step_type(step)

    if stype == "agent":
        lines.append(f'{pad}{sid}(["{label}"])')
    elif stype == "prompt_part":
        lines.append(f'{pad}{sid}>"{label}"]')
    else:
        lines.append(f'{pad}{sid}["{label}"]')


def _emit_node(step: WorkflowStep, lines: list[str]) -> None:
    """Append Mermaid node declaration(s) for a step."""
    if step.parallel_config:
        sid = _mermaid_id(step.name)
        label = _escape_label(step.name)
        flow = control_annotations(step)
        if flow:
            label += f"<br/>{flow}"
        lines.append(f'    subgraph {sid}["{label}"]')
        for sub in step.parallel_config.steps:
            _emit_leaf(sub, lines, indent=8)
        lines.append("    end")
    else:
        _emit_leaf(step, lines)


def workflow_to_mermaid(workflow: Workflow) -> str:
    """Generate a ``graph TD`` Mermaid flowchart from *workflow*."""
    all_names = collect_all_step_names(workflow.steps)
    lines: list[str] = ["graph TD"]

    for step in workflow.steps:
        _emit_node(step, lines)

    for step in workflow.steps:
        refs = extract_step_references(step, all_names)
        target = _mermaid_id(step.name)
        for ref in sorted(refs):
            lines.append(f"    {_mermaid_id(ref)} --> {target}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Text summary
# ---------------------------------------------------------------------------


def workflow_to_text(workflow: Workflow) -> str:
    """Generate a plain-text summary of *workflow*."""
    out: list[str] = [f"Workflow: {workflow.name}"]
    if workflow.source_path:
        out.append(f"Source: {workflow.source_path}")

    explicit = [i for i in workflow.inputs if not getattr(i, "is_step_input", False)]
    if explicit:
        out.append("")
        out.append("Inputs:")
        for inp in explicit:
            out.append(f"  - {inp.name}: {inp.type.value}")

    out.append("")
    out.append("Steps:")
    all_names = collect_all_step_names(workflow.steps)
    for i, step in enumerate(workflow.steps, 1):
        stype = step_type(step)
        flow = control_annotations(step)
        line = f"  {i}. {step.name} [{stype}]"
        if flow:
            line += f"  {flow}"
        out.append(line)

        if step.parallel_config:
            for sub in step.parallel_config.steps:
                out.append(f"     - {sub.name} [{step_type(sub)}]")

        refs = extract_step_references(step, all_names)
        if refs:
            out.append(f"     depends on: {', '.join(sorted(refs))}")

    return "\n".join(out)


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def list_workflows(workflows: dict[str, Workflow]) -> str:
    """Tabular listing of available workflows with step counts."""
    if not workflows:
        return "No workflows found."

    multi = {n: w for n, w in workflows.items() if not w.is_simple_xprompt()}
    if not multi:
        return "No multi-step workflows found."

    rows: list[tuple[str, str, str]] = []
    for name in sorted(multi):
        wf = multi[name]
        rows.append((name, str(len(wf.steps)), wf.source_path or ""))

    name_w = max(len("Name"), max(len(r[0]) for r in rows))
    count_w = max(len("Steps"), max(len(r[1]) for r in rows))

    header = f"{'Name':<{name_w}}  {'Steps':>{count_w}}  Source"
    sep = "-" * len(header)
    lines = [header, sep]
    for name, count, source in rows:
        lines.append(f"{name:<{name_w}}  {count:>{count_w}}  {source}")

    return "\n".join(lines)
