"""Unit tests for the ``sase plan search`` renderers (Phase 5).

These drive :mod:`sase.main.plan_search_render` directly off hand-built
:class:`~sase.plan_search.model.PlanSearchMatch` objects (no Rust dependency),
covering source grouping, status/kind icons, snippet selection + truncation,
the markdown tables, panel rendering, empty results, and ``--color`` handling.
"""

from __future__ import annotations

import io

from sase.main import plan_search_render as R
from sase.plan_search.model import Plan, PlanSearchMatch


def _match(
    *,
    source: str = "repo",
    kind: str = "tale",
    relpath: str = "plans/202606/auth_token_refresh.md",
    name: str = "auth_token_refresh",
    title: str = "Refresh auth tokens on 401",
    status: str = "wip",
    created_at: str = "2026-06-18T21:29:20",
    prompt_link: str = "",
    summary: str = "Retry the request once after refreshing the auth token.",
    body: str = "",
    frontmatter: dict[str, str] | None = None,
    matched_fields: list[str] | None = None,
    score: float = 100.0,
) -> PlanSearchMatch:
    plan = Plan(
        source=source,
        kind=kind,
        path=f"/abs/{relpath}",
        relpath=relpath,
        name=name,
        title=title,
        status=status,
        created_at=created_at,
        prompt_link=prompt_link,
        summary=summary,
        body=body or f"# {title}\n\n{summary}\n",
        frontmatter=frontmatter or {},
    )
    return PlanSearchMatch(
        plan=plan,
        matched_fields=matched_fields if matched_fields is not None else ["title"],
        score=score,
    )


def _compact(matches: list[PlanSearchMatch], *, query: str | None = "auth") -> str:
    buf = io.StringIO()
    console = R._make_console("never", file=buf, width=100)
    R._render_compact(matches, query=query, sort_label="relevance", console=console)
    return buf.getvalue()


# --- helpers -------------------------------------------------------------


def test_display_path_strips_repo_kind_dir_and_extension() -> None:
    plan = _match(relpath="plans/202606/auth_token_refresh.md").plan
    assert R._display_path(plan) == "202606/auth_token_refresh"


def test_display_path_keeps_local_shard_and_handles_flat() -> None:
    sharded = _match(source="local", relpath="202604/auth_login_fix.md").plan
    flat = _match(source="local", relpath="flat_note.md").plan
    assert R._display_path(sharded) == "202604/auth_login_fix"
    assert R._display_path(flat) == "flat_note"


def test_repo_source_root_label_reflects_local_sdd_store() -> None:
    match = _match(relpath="plans/202607/store_plan.md")
    match.plan.path = "/repo/.sase/sdd/plans/202607/store_plan.md"

    assert R._source_root_label("repo", [match]) == ".sase/sdd/"


def test_status_icons_use_bead_vocabulary() -> None:
    assert R._status_icon("wip") == "◐"
    assert R._status_icon("done") == "✓"
    assert R._status_icon("") == "○"
    assert R._status_icon("mystery") == "○"


def test_kind_styles_preserve_fixed_kinds_and_hash_document_roles() -> None:
    assert R._kind_style("tale") == "cyan"
    assert R._kind_style("epic") == "magenta"
    assert R._kind_style("local") == "bright_black"
    assert R._kind_style("designs") == R._kind_style("designs")
    assert R._kind_style("designs") in R._DOCUMENT_KIND_STYLES
    assert R._kind_style("research") in R._DOCUMENT_KIND_STYLES


def test_single_line_snippet_centers_and_truncates_on_query() -> None:
    value = "x" * 80 + " findme " + "y" * 80
    snippet = R._single_line_snippet(value, "findme", max_chars=40)
    assert "findme" in snippet
    assert snippet.startswith("…") and snippet.endswith("…")
    assert len(snippet) <= 42  # max_chars plus the two ellipsis glyphs


def test_single_line_snippet_without_query_uses_first_line() -> None:
    assert R._single_line_snippet("first line\nsecond line", None) == "first line"
    assert R._single_line_snippet("   \n  \n", "x") == ""


def test_snippet_source_skips_heading_only_body_hits() -> None:
    # The only "auth" in the body is the markdown H1; prefer the clean summary.
    match = _match(
        title="Unified auth",
        summary="Consolidate the providers behind one interface.",
        body="# Unified auth\n\nConsolidate the providers behind one interface.\n",
        matched_fields=["title", "body"],
    )
    assert R._snippet_source(match, "auth") == (
        "Consolidate the providers behind one interface."
    )


# --- compact -------------------------------------------------------------


def test_compact_groups_repo_above_local_with_footer() -> None:
    out = _compact(
        [
            _match(),
            _match(
                source="local",
                kind="local",
                relpath="202604/auth_login_fix.md",
                name="auth_login_fix",
                title="Fix login auth race",
                status="done",
                summary="Guard the auth session write behind a lock.",
            ),
        ]
    )
    assert "REPO" in out and "LOCAL" in out
    assert out.index("REPO") < out.index("LOCAL")
    assert "◐" in out and "✓" in out
    assert "202606/auth_token_refresh" in out
    assert "2 plans · 1 repo · 1 local · sorted by relevance" in out


def test_compact_single_source_footer_omits_breakdown() -> None:
    out = _compact([_match()])
    assert out.rstrip().endswith("1 plan · sorted by relevance")
    assert "repo" not in out.rstrip().splitlines()[-1]


def test_compact_shows_highlighted_snippet_line() -> None:
    out = _compact([_match()])
    assert "Retry the request once after refreshing the auth token." in out


def test_compact_empty_results_message() -> None:
    assert _compact([], query="zzz").strip() == 'No plans match "zzz".'
    assert _compact([], query=None).strip() == "No plans found."


# --- color ---------------------------------------------------------------


def test_color_always_emits_ansi() -> None:
    buf = io.StringIO()
    console = R._make_console("always", file=buf, width=100)
    R._render_compact([_match()], query="auth", sort_label="relevance", console=console)
    assert "\x1b[" in buf.getvalue()


def test_color_never_strips_ansi() -> None:
    assert "\x1b[" not in _compact([_match()])


def test_color_auto_on_non_tty_has_no_ansi() -> None:
    buf = io.StringIO()  # StringIO is not a TTY → auto resolves to no color
    console = R._make_console("auto", file=buf, width=100)
    R._render_compact([_match()], query="auth", sort_label="relevance", console=console)
    assert "\x1b[" not in buf.getvalue()


# --- full ----------------------------------------------------------------


def test_full_panel_includes_metadata_and_excerpt() -> None:
    buf = io.StringIO()
    console = R._make_console("never", file=buf, width=100)
    R._render_full(
        [
            _match(
                prompt_link="sdd/prompts/202606/x.md", matched_fields=["title", "body"]
            )
        ],
        query="auth",
        console=console,
    )
    out = buf.getvalue()
    assert "╭" in out and "╰" in out  # bordered panel
    assert "Refresh auth tokens on 401" in out
    assert "Kind" in out and "Status" in out and "Score" in out
    assert "sdd/prompts/202606/x.md" in out
    assert "title, body" in out


def test_full_empty_results_message() -> None:
    buf = io.StringIO()
    console = R._make_console("never", file=buf, width=100)
    R._render_full([], query="zzz", console=console)
    assert buf.getvalue().strip() == 'No plans match "zzz".'


# --- markdown ------------------------------------------------------------


def test_markdown_structure_groups_and_tables() -> None:
    md = R._render_markdown(
        [
            _match(),
            _match(
                source="local",
                kind="local",
                relpath="202604/auth_login_fix.md",
                name="auth_login_fix",
                title="Fix login auth race",
                status="done",
            ),
        ],
        query="auth",
        sort_label="relevance",
    )
    assert md.startswith("# Plan Search Results")
    assert "**Query:** `auth`" in md
    assert "Found 2 plans · 1 repo · 1 local · sorted by relevance" in md
    assert "## REPO — sdd/" in md
    assert "## LOCAL — ~/.sase/plans/" in md
    assert "| Status | Kind | Plan | Title | Created |" in md
    assert "| ◐ wip | tale | `202606/auth_token_refresh` |" in md
    assert md.index("## REPO") < md.index("## LOCAL")


def test_markdown_browse_mode_omits_query_line() -> None:
    md = R._render_markdown(
        [_match(matched_fields=[])], query=None, sort_label="recent"
    )
    assert "**Query:**" not in md
    assert "sorted by recent" in md


def test_markdown_escapes_pipes_in_title() -> None:
    md = R._render_markdown(
        [_match(title="a | b")], query="auth", sort_label="relevance"
    )
    assert "a \\| b" in md


def test_markdown_empty_results_message() -> None:
    assert "No plans match `zzz`." in R._render_markdown(
        [], query="zzz", sort_label="relevance"
    )
    assert "No plans found." in R._render_markdown([], query=None, sort_label="recent")
