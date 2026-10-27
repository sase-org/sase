"""Show and audited-read handlers for the bead CLI."""

from __future__ import annotations

import argparse
import os
import shlex
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from sase.agent.names._registry import name_registry_load_session
from sase.bead.bead_views import SASE_BEAD_SKIP_VIEW_LOG
from sase.bead.cli_common import get_read_view
from sase.bead.cli_detail import (
    artifact_reference_context,
    design_paths_are_relative,
    plan_reference_roots,
    render_issue_detail,
    resolve_bead_creator_url,
    resolve_bead_page_url,
)
from sase.bead.cli_detail_links import NO_LINKS_RECOVERY_HINT
from sase.bead.cli_detail_resolution import IssueDetail
from sase.bead.cli_detail_style import DetailStyle, resolve_detail_style
from sase.bead.cli_show_batch import (
    ARTIFACT_LINK_NEIGHBORHOOD_ERRORS,
    artifact_link_neighborhood_detail,
    build_show_batch_document,
    default_show_render_context_resolver,
    render_show_batch,
    render_show_document,
    resolve_show_batch,
)
from sase.bead.cli_show_router import ShowStoreRouter, ShowStoreRoutingError
from sase.main.parser_bead_common import resolve_wrap_width
from sase.cli_pager import PagerMode, page_or_print, resolve_pager_mode
from sase.markdown_width import markdown_print_width
from sase.repo_inventory import repo_inventory_session


def handle_bead_show(args: argparse.Namespace) -> None:
    """Show beads for interactive human use; agents are refused to `read`."""
    _refuse_agent_bead_show(args)
    _run_bead_view(args, audited_reason=None)


def _refuse_agent_bead_show(
    args: argparse.Namespace, argv: Sequence[str] | None = None
) -> None:
    """Refuse agent-run `sase bead show` with the matching `read` command.

    Fires under exactly the condition that used to write a `viewed` row:
    an agent identity is present and `SASE_BEAD_SKIP_VIEW_LOG` is not `"1"`.
    Automation inside agents already sets that variable, and interactive
    human use has no agent identity, so neither is affected.
    """
    from sase.bead.attribution import acting_agent_name

    if os.environ.get(SASE_BEAD_SKIP_VIEW_LOG) == "1":
        return
    if not acting_agent_name():
        return
    tokens = list(argv) if argv is not None else sys.argv[1:]
    tail: list[str] | None = None
    try:
        bead_index = tokens.index("bead")
        show_index = tokens.index("show", bead_index + 1)
        tail = tokens[show_index + 1 :]
    except ValueError:
        tail = None
    if not tail:
        tail = _show_ids(args)
    suggestion = shlex.join(
        ["sase", "bead", "read", *tail, "-r", "<why you need this bead>"]
    )
    print(
        "Error: agents must read beads with `sase bead read`, which records why you read them:\n"
        f"  {suggestion}\n"
        "`sase bead read` accepts the same IDs and options as `sase bead show`; "
        "`show` is the human command.",
        file=sys.stderr,
    )
    sys.exit(2)


def handle_bead_read(args: argparse.Namespace) -> None:
    """Read beads after recording an audited, reasoned read."""
    _run_bead_view(args, audited_reason=str(getattr(args, "reason", "")))


def _run_bead_view(args: argparse.Namespace, *, audited_reason: str | None) -> None:
    from sase.bead.attachments.fetch import FetchMode, fetch_context

    fetch_mode: FetchMode
    if bool(getattr(args, "download", False)):
        fetch_mode = "force"
    elif getattr(args, "format", "full") in ("full", "json"):
        fetch_mode = "auto"
    else:
        fetch_mode = "never"
    with fetch_context(mode=fetch_mode):
        _run_bead_view_inner(args, audited_reason=audited_reason)


def _run_bead_view_inner(
    args: argparse.Namespace, *, audited_reason: str | None
) -> None:
    include_links = not bool(getattr(args, "no_links", False))
    ids = _show_ids(args)
    style = resolve_detail_style(
        style=getattr(args, "style", "auto"),
        color=getattr(args, "color", "auto"),
    )
    wrap = resolve_wrap_width(getattr(args, "wrap", markdown_print_width()))
    pager_mode: PagerMode = resolve_pager_mode(getattr(args, "pager", "auto"))
    pager_document = None
    is_show = audited_reason is None
    images_mode = "never"
    images_hint: str | None = None
    if is_show and getattr(args, "format", "full") == "full":
        try:
            from sase.bead.show_images import resolve_images_mode

            cli_images = getattr(args, "images", None)
            images_mode, images_hint = resolve_images_mode(
                cli_images,
                is_tty=sys.stdout.isatty(),
                env=dict(os.environ),
            )
        except Exception:
            images_mode, images_hint = "never", None
    if getattr(args, "format", "full") != "full":
        images_mode, images_hint = "never", None
    if images_mode == "kitty":
        pager_mode = PagerMode.NEVER

    render_context_for = default_show_render_context_resolver(
        design_paths_are_relative_fn=design_paths_are_relative,
        plan_reference_roots_fn=plan_reference_roots,
        artifact_reference_context_fn=artifact_reference_context,
        resolve_bead_creator_url_fn=resolve_bead_creator_url,
        resolve_bead_page_url_fn=resolve_bead_page_url,
    )

    with (
        repo_inventory_session(),
        name_registry_load_session(),
        _show_read_view() as view,
    ):
        try:
            with ShowStoreRouter(
                view,
                project_ref=getattr(args, "project", None),
            ) as router:
                batch = resolve_show_batch(
                    view,
                    ids,
                    format_name=args.format,
                    include_links=include_links,
                    detail_enricher=(
                        _with_artifact_link_neighborhood if include_links else None
                    ),
                    router=router,
                )
        except ShowStoreRoutingError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        if args.format == "full":
            document = build_show_batch_document(
                batch,
                style=style,
                wrap=wrap,
                render_context_for=render_context_for,
                images_mode=images_mode,
            )
            pager_document = document
            body = render_show_document(document, style=style, wrap=wrap)
        else:
            body = render_show_batch(
                batch,
                format_name=args.format,
                include_links=include_links,
                style=style,
                wrap=wrap,
                render_context_for=render_context_for,
                images_mode="never",
            )
        if audited_reason is not None:
            _record_bead_reads_before_print(batch, reason=audited_reason)
            from sase.bead.assigned_near_miss import apply_read_near_miss

            body, pager_document = apply_read_near_miss(
                body,
                batch,
                format_name=args.format,
                pager_document=pager_document,
            )

    if images_hint and sys.stderr.isatty():
        print(f"\x1b[2m{images_hint}\x1b[0m", file=sys.stderr)
    elif images_hint:
        print(images_hint, file=sys.stderr)
    if body:
        page_or_print(body, mode=pager_mode, document=pager_document)
    if images_mode == "kitty" and is_show and getattr(args, "format", "full") == "full":
        _emit_kitty_attachment_pixels(batch)
    for failure in batch.failures:
        message = failure.message
        if audited_reason is not None:
            from sase.bead.assigned_near_miss import annotate_not_found_message

            message = annotate_not_found_message(
                message, requested=failure.requested_id
            )
        print(f"Error: {message}", file=sys.stderr)
    if batch.failures:
        sys.exit(1)


def _emit_kitty_attachment_pixels(batch: Any) -> None:
    """Emit kitty-graphics pixels for cached raster attachments, bypassing pager."""
    try:
        from sase.bead.show_images import (
            MAX_THUMBS_PER_NOTE,
            is_previewable_raster,
            kitty_escape_for_path,
        )
        from sase.bead.attachment_presentation import (
            attachment_availability,
            attachment_view_path,
        )
    except Exception:
        return
    for entry in getattr(batch, "entries", ()):
        issue = getattr(entry, "issue", None)
        if issue is None:
            continue
        for note in getattr(issue, "notes", ()):
            emitted = 0
            for attachment in getattr(note, "attachments", ()):
                if emitted >= MAX_THUMBS_PER_NOTE:
                    break
                name = str(getattr(attachment, "name", ""))
                mime_type = str(getattr(attachment, "mime_type", ""))
                sha256 = str(getattr(attachment, "sha256", ""))
                if not name or not sha256:
                    continue
                if not is_previewable_raster(name, mime_type):
                    continue
                if attachment_availability(sha256) != "cached":
                    continue
                try:
                    view = attachment_view_path(sha256, name)
                except Exception:
                    continue
                if view is None:
                    continue
                escape = kitty_escape_for_path(view)
                if escape:
                    sys.stdout.write(escape + "\n")
                    emitted += 1


def _record_bead_reads_before_print(batch: Any, *, reason: str) -> None:
    """Append audited bead reads and queue best-effort read links."""
    from sase.artifact_read_links import (
        READ_NOT_RECORDED_NOTE,
        should_record_read_link,
    )
    from sase.artifact_read_log import ArtifactReadError
    from sase.bead.bead_reads import (
        bead_read_ref,
        queue_bead_read_links,
        record_bead_reads,
    )

    # Canonicalize once so the audit rows and the read-link edges below
    # share one stable ref per bead.
    try:
        refs = [bead_read_ref(str(entry.issue.id)) for entry in batch.entries]
        record_bead_reads(refs, reason=reason)
    except ArtifactReadError as exc:
        print(f"sase bead read: {exc}", file=sys.stderr)
        sys.exit(1)
    if should_record_read_link():
        try:
            queue_bead_read_links(refs, reason=reason)
        except Exception as exc:  # noqa: BLE001 - beads still print
            print(f"Error: could not record read link: {exc}", file=sys.stderr)
    else:
        print(READ_NOT_RECORDED_NOTE, file=sys.stderr)


@contextmanager
def _show_read_view() -> Iterator[Any | None]:
    """Yield the local show view without creating a caller bead store."""
    from sase.bead.operation_context import local_operation_context

    context = local_operation_context(require_existing=True)
    if context is None:
        yield None
        return
    with get_read_view(bead_context=context) as view:
        yield view


def _show_ids(args: argparse.Namespace) -> list[str]:
    ids = getattr(args, "ids", None)
    if ids is not None:
        return list(ids)
    return [str(args.id)]


def _with_artifact_link_neighborhood(detail: IssueDetail) -> IssueDetail:
    try:
        return artifact_link_neighborhood_detail(detail)
    except ARTIFACT_LINK_NEIGHBORHOOD_ERRORS as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print(f"Hint: {NO_LINKS_RECOVERY_HINT}.", file=sys.stderr)
        sys.exit(1)
