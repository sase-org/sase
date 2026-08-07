"""Shared preview-recovery algorithm for TaskTriage and BeadSnooze gates.

Neither gate's payload carries the agent-authored description and notes, so
validation recovers them from the persisted preview instead: render a
marker-bearing template, slice the preview between the prefix and suffix the
markers delimit, then recover ``(description, notes)`` from the sliced body
and confirm re-rendering it reproduces the preview byte for byte. That final
byte-for-byte comparison — not the prefix/suffix slice — is what stops an
injected preview from passing, since the renderer is a pure function of only
those two free-form fields.

Two recovery candidates are tried because the renderer omits the ``## Notes``
heading entirely when notes are blank, so the body no longer always contains
the ``\\n\\n## Notes\\n\\n`` separator:

- candidate A: the body contains the separator, so split on it to recover
  ``(description, notes)``. This is the only shape a preview persisted before
  blank notes were omitted can take.
- candidate B: the separator is absent (or candidate A's re-render does not
  match), so treat the whole body as the description and notes as ``""``.
  This is the shape a fresh blank-notes preview takes, and as a side effect
  also recovers previews whose description itself happens to contain the
  separator text.
"""

from __future__ import annotations

from collections.abc import Callable


def preview_matches_renderer(
    *,
    render: Callable[[str, str], str],
    description_marker: str,
    notes_marker: str,
    preview_content: str | None,
) -> bool:
    """Return whether ``preview_content`` is a possible output of ``render``.

    ``render`` closes over every other payload field and renders a preview
    from just ``(description, notes)``.
    """
    template = render(description_marker, notes_marker)
    preview_prefix, marker, template_tail = template.partition(description_marker)
    description_notes_separator, marker_two, preview_suffix = template_tail.partition(
        notes_marker
    )
    if not (
        marker
        and marker_two
        and isinstance(preview_content, str)
        and preview_content.startswith(preview_prefix)
        and preview_content.endswith(preview_suffix)
    ):
        return False
    body_end = len(preview_content) - len(preview_suffix)
    preview_body = preview_content[len(preview_prefix) : body_end]
    description, separator, notes = preview_body.partition(description_notes_separator)
    if separator and render(description, notes) == preview_content:
        return True
    return render(preview_body, "") == preview_content
