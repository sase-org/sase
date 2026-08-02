"""``sase prompt export``/``save`` — bridge prompts into durable files.

``export`` is a full-text escape hatch (like ``show``/``copy``): it prints a
prompt to stdout or writes it to a chosen file. ``save`` writes an ordinary
markdown xprompt file that the existing loader can resolve via ``#name``. The
retired ``--sdd`` spelling remains parseable only to explain the canonical
agents-sidecar archive and direct users to safe replacements.

Neither command touches the prompt-history store, so they need no lock; their
only safety guard is that an existing destination is never silently overwritten
without ``--force``.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from sase.history.prompt import (
    PromptHistoryRecord,
    PromptSelectorError,
    resolve_prompt_selector,
)
from sase.prompt.render import prompt_preview

# Where metadata-wrapped local-history exports say they came from.
_SOURCE_LABEL = "sase prompt history"

# Frontmatter key for free-form user tags. The reserved ``tags`` key is limited
# to the semantic ``XPromptTag`` enum, so writing arbitrary ``--tag`` values
# there would make the xprompt loader raise; ``prompt_tags`` is ignored by the
# loader and therefore safe to round-trip.
_USER_TAGS_KEY = "prompt_tags"

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_SLUG_MAX_LEN = 48


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    """Return a clean, hyphen-separated slug from a prompt's preview text."""
    base = prompt_preview(text, limit=200)
    slug = _SLUG_RE.sub("-", base.lower()).strip("-")
    if len(slug) > _SLUG_MAX_LEN:
        slug = slug[:_SLUG_MAX_LEN].rstrip("-")
    return slug


def _yaml_frontmatter(data: dict[str, object]) -> str:
    """Render *data* as a ``---``-delimited YAML frontmatter block.

    ``sort_keys=False`` preserves the caller's stable, human-readable order;
    ``yaml.safe_dump`` quotes timestamp-like and otherwise ambiguous values so
    they round-trip back as strings.
    """
    dumped = yaml.safe_dump(
        data, sort_keys=False, allow_unicode=True, default_flow_style=False
    )
    return f"---\n{dumped}---\n"


def _resolve_or_exit(selector: str, *, prog: str) -> PromptHistoryRecord:
    try:
        return resolve_prompt_selector(selector)
    except PromptSelectorError as exc:
        print(f"{prog}: {exc}", file=sys.stderr)
        sys.exit(2)


def _reject_path_token(value: str, *, label: str, prog: str) -> None:
    """Reject names/projects that could escape their target directory."""
    if not value or "/" in value or "\\" in value or ".." in value:
        print(f"{prog}: invalid {label}: {value!r}", file=sys.stderr)
        sys.exit(2)


def _write_file_or_exit(dest: Path, content: str, *, force: bool, prog: str) -> None:
    """Write *content* to *dest*, refusing to clobber an existing file."""
    if dest.exists() and not force:
        print(
            f"{prog}: refusing to overwrite existing file {dest}."
            " Re-run with --force to replace it.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not content.endswith("\n"):
        content += "\n"
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    except OSError as exc:
        print(f"{prog}: failed to write {dest}: {exc}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


def handle_prompt_export(args: argparse.Namespace) -> None:
    """Export a prompt to stdout or a chosen file."""
    prog = "sase prompt export"
    selector: str = getattr(args, "id", "")
    out: str | None = getattr(args, "out", None)
    sdd = bool(getattr(args, "sdd", False))
    force = bool(getattr(args, "force", False))
    metadata = bool(getattr(args, "metadata", False))

    if sdd:
        print(
            f"{prog}: --sdd is retired because canonical archived prompts must"
            " come from agent runs with captured provenance. Use --out PATH for"
            " a local-history export, or `sase agent prompts` to inspect the"
            " canonical agents-sidecar archive.",
            file=sys.stderr,
        )
        sys.exit(2)

    record = _resolve_or_exit(selector, prog=prog)

    include_metadata = metadata
    content = _build_export_content(record, metadata=include_metadata)

    if out is not None:
        dest = Path(out).expanduser()
        _write_file_or_exit(dest, content, force=force, prog=prog)
        print(f"Exported {record.id} to {dest}.")
        return

    # stdout: keep the no-metadata path byte-exact (like `show -f raw`); only
    # the metadata path guarantees a trailing newline for readability.
    sys.stdout.write(content)
    if include_metadata and not content.endswith("\n"):
        sys.stdout.write("\n")


def _build_export_content(record: PromptHistoryRecord, *, metadata: bool) -> str:
    if not metadata:
        return record.text
    block = _yaml_frontmatter(
        {
            "id": record.id,
            "sha256": record.text_sha256,
            "timestamp": record.timestamp,
            "last_used": record.last_used,
            "cancelled": record.cancelled,
            "source": _SOURCE_LABEL,
        }
    )
    return f"{block}\n{record.text}"


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------


def handle_prompt_save(args: argparse.Namespace) -> None:
    """Save a prompt as a reusable markdown xprompt file."""
    prog = "sase prompt save"
    selector: str = getattr(args, "id", "")
    name: str | None = getattr(args, "name", None)
    description: str | None = getattr(args, "description", None)
    project: str | None = getattr(args, "project", None)
    use_global = bool(getattr(args, "global_", False))
    force = bool(getattr(args, "force", False))
    tags: list[str] = list(getattr(args, "tag", None) or [])

    if use_global and project is not None:
        print(
            f"{prog}: --global and --project choose different destinations;"
            " pass only one.",
            file=sys.stderr,
        )
        sys.exit(2)

    record = _resolve_or_exit(selector, prog=prog)

    if name is None:
        # A deterministic slug keeps repeated saves of the same prompt stable;
        # the prompt ID is the fallback when the prompt has no usable preview.
        slug = _slugify(record.text)
        name = slug or record.id
    else:
        _reject_path_token(name, label="name", prog=prog)

    target_dir = _save_target_dir(project=project, use_global=use_global, prog=prog)
    dest = target_dir / f"{name}.md"

    content = _build_save_content(record, name=name, description=description, tags=tags)
    _write_file_or_exit(dest, content, force=force, prog=prog)

    run_ref = f"{project}/{name}" if project else name
    print(f'Saved xprompt {name!r} to {dest}. Run it with: sase run "#{run_ref}"')


def _save_target_dir(*, project: str | None, use_global: bool, prog: str) -> Path:
    from sase.content_layout import (
        discover_project_root,
        resolve_home_layout,
        resolve_project_layout,
    )

    if project is not None:
        _reject_path_token(project, label="project", prog=prog)
        return resolve_home_layout().xprompts.write_path / project
    if use_global:
        return resolve_home_layout().xprompts.write_path
    root = discover_project_root() or Path.cwd()
    return resolve_project_layout(root).xprompts.write_path


def _build_save_content(
    record: PromptHistoryRecord,
    *,
    name: str,
    description: str | None,
    tags: list[str],
) -> str:
    front: dict[str, object] = {
        "name": name,
        # Default description is the cleaned one-line preview so the saved
        # xprompt is self-describing in catalogs; --description overrides it.
        "description": description
        if description is not None
        else prompt_preview(record.text),
    }
    if tags:
        front[_USER_TAGS_KEY] = tags
    return f"{_yaml_frontmatter(front)}\n{record.text}"
