---
create_time: 2026-05-11 20:42:15
status: wip
prompt: sdd/prompts/202605/review_telegram_blog_post.md
---
# Plan: Review and polish the Telegram mobile blog insertion

## Context

The previous change inserted a new Post 8, `docs/blog/posts/telegram-mobile-agents.md`, before the prior final roadmap
post. It also renumbered `whats-next-memory-mobile-web.md` to Post 9 and updated the blog index, series hub, Post 7
navigation, and MkDocs nav.

I reviewed those docs against the sibling `../sase-telegram` plugin source and documentation. The shape of the prior
work is sound: the post is in the right slot, the navigation is mostly consistent, and the core feature set matches the
plugin. The remaining work should be polish and factual tightening, not a rewrite.

## Goals

- Preserve the prior agent's structure: Telegram remains Post 8 and What's Next remains Post 9.
- Tighten the Telegram post where implementation details are slightly imprecise:
  - avoid implying there is no Telegram state at all, since the plugin uses pending action, feedback, offset, rate, and
    image state files;
  - describe the outbound attachment behavior more accurately: Markdown attachments are rendered to PDF when possible,
    existing PDFs are sent as documents, and images are sent inline;
  - mention the launch conveniences that are useful from a phone: code marker reconstruction, `#gh@sase` shorthand
    normalization, and remembered project context for `/bead`;
  - describe `/xprompts` as a PDF catalog export, matching the plugin docs;
  - clarify `/bead` project selection and the disabled-launch host behavior.
- Fix small reader-facing copy issues in the series hub and adjacent roadmap post if encountered during the pass.
- Verify strict docs/build checks and the repository's required `just check` after edits.

## Non-Goals

- Do not change post slugs, dates, or the published series order.
- Do not edit SASE memory files.
- Do not modify the `../sase-telegram` plugin repo unless the review uncovers an implementation defect; the current
  expected work is documentation-only in this repo.
- Do not add a second Telegram post or turn Post 8 into a reference manual.

## Implementation Steps

1. Edit `docs/blog/posts/telegram-mobile-agents.md` with a narrow factual-polish pass:
   - soften the state-machine sentence;
   - add the missing launch and slash-command details;
   - adjust attachment/PDF wording to match `../sase-telegram/docs/outbound.md`;
   - keep the prose blog-like rather than exhaustive.
2. Edit `docs/series/agentic-software-engineering.md` to fix the "After the two posts" phrasing in Reader Paths.
3. Optionally make one small clarity edit in `docs/blog/posts/whats-next-memory-mobile-web.md` if the Post 8/Post 9
   bridge still reads awkwardly after the Telegram edits.
4. Run link/build checks, then run `just check` as required by `memory/short/build_and_run.md`.
5. Inspect the final diff to ensure the changes are limited to docs plus this plan file.

## Verification

- `just install` first, because this workspace may be stale.
- `just docs-check` or the closest available docs build target to catch broken MkDocs links.
- `just check` before final response.
- Review `git diff --check` and `git diff --stat`.

## Risk

The main risk is over-documenting the post and turning it into a duplicate of `sase-telegram`'s README. Keep the changes
targeted at correctness and the mobile workflow story.
