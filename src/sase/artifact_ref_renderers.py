"""Ref renderer registry and Jinja protection helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

from sase.artifact_ref_models import ArtifactRefContext
from sase.sidecar_ref_config import DEFAULT_DOCUMENT_REF_RENDERER, canonical_ref_input
from sase.xprompt.models import InputArg, InputType, XPrompt


@dataclass(slots=True)
class ArtifactRendererJinjaProtection:
    """Protect Jinja delimiters emitted by artifact renderers."""

    replacements: list[tuple[str, str]] = field(default_factory=list)

    def protect(self, text: str) -> str:
        protected = text
        for delimiter in _JINJA_DELIMITERS:
            while delimiter in protected:
                placeholder = f"\x00SASE_ARTIFACT_JINJA_{len(self.replacements)}\x00"
                self.replacements.append((placeholder, delimiter))
                protected = protected.replace(delimiter, placeholder, 1)
        return protected

    def unprotect(self, text: str) -> str:
        restored = text
        for placeholder, delimiter in reversed(self.replacements):
            restored = restored.replace(placeholder, delimiter)
        return restored


_JINJA_DELIMITERS = ("{{", "}}", "{%", "%}", "{#", "#}")


def ref_renderer_registry(context: ArtifactRefContext) -> dict[str, XPrompt]:
    from sase.xprompt.loader_refs import load_ref_xprompts

    registry = load_ref_xprompts(project=_context_project(context))
    for document_root in context.document_roots:
        name = f"ref/{document_root.kind}"
        if name not in registry:
            registry[name] = generated_document_ref_xprompt(document_root.kind)
    return registry


def generated_document_ref_xprompt(kind: str) -> XPrompt:
    input_name = canonical_ref_input(kind)
    return XPrompt(
        name=f"ref/{kind}",
        content=DEFAULT_DOCUMENT_REF_RENDERER,
        inputs=[InputArg(name=input_name, type=_ref_input_type(input_name))],
        source_path=f"generated_sidecar_ref:{kind}",
        description=f"Generated document renderer for {kind}",
        ref=True,
        ref_kind=kind,
        ref_sidecar_role=kind,
    )


def _ref_input_type(name: str) -> InputType:
    if name == "file_path":
        return InputType.PATH
    if name == "agent_name":
        return InputType.AGENT
    if name in {"artifact_id", "bug", "commit"}:
        return InputType.LINE
    return InputType.WORD


def _context_project(context: ArtifactRefContext) -> str | None:
    if len(context.projects) == 1:
        return context.projects[0].name
    return None


__all__ = [
    "ArtifactRendererJinjaProtection",
    "generated_document_ref_xprompt",
    "ref_renderer_registry",
]
