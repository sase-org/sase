---
create_time: 2026-05-11 17:07:53
status: done
prompt: sdd/prompts/202605/fix_recent_ci_failures.md
---
# Plan: Fix Recent GitHub Actions Failures on master

## Context

Three independent CI failure categories are red on master (and have been since at least 8 commits ago). The user asked
to fix them together but each has a different root cause, a different fix surface, and one even lives in a sibling repo.
The plan below sequences the work so the cheapest, most-localized fixes go first and the visual-snapshot work (which
requires human judgment about what is a real regression vs. an intentional rendering change) goes last.

## Failure inventory

| #   | Job (workflow)                     | Symptom                                                                                                                              | Root cause                                                                                                                                                                                                                                                                                                                                               | Fix location                               |
| --- | ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| 1   | `bead-backend` (CI)                | `cargo fmt --all -- --check` exits 1                                                                                                 | rustfmt wants different line breaks in `pub use mobile::{…}` and `use sase_core::notifications::{…}` after recent imports were added/reordered                                                                                                                                                                                                           | **Sibling `../sase-core`** (NOT this repo) |
| 2   | `Build docs PDF` (Deploy Docs)     | `tools/postprocess_docs_pdf` aborts with `missing generated HTML: site/blog/posts/why-coding-agents-need-orchestration/index.html`   | Commit `6b7b26ad` added two `blog/posts/*.md` files to `mkdocs.yml` `nav`, but the mkdocs-material `blog` plugin already owns those pages and re-routes them (with `post_url_format: "{slug}"` → `site/blog/<slug>/index.html`, not `site/blog/posts/<slug>/…`). The PDF post-processor walks `nav` and demands HTML at the literal `blog/posts/…` path. | **This repo** (`sase_102`)                 |
| 3   | `visual-test` + `test (3.14)` (CI) | 7 PNG snapshot mismatches in `tests/ace/tui/visual/test_ace_png_snapshots.py` (~6.5% pixel diff on `changespec_initial_120x40` etc.) | Snapshots were last regenerated at commit `c3a4f0f0` ("extend unread chip…"). Several feature commits have since touched ACE rendering, most recently `487a0c20`/`b9bf9b9b` (chop run history) which extended cache state visible to ACE. Drift is almost certainly intentional, but a human (you) needs to eyeball the diffs before we bless them.      | **This repo** (`sase_102`)                 |

Confirmed locally:

- Ran `cargo fmt --all -- --check` in `../sase-core` and reproduced the same two diffs.
- Diff of `mkdocs.yml` at `6b7b26ad` shows the two blog posts being added to `nav`; Deploy Docs went from green ➜ red on
  that exact commit (last green: `feat: make the 'other' model alias override-aware`, first red:
  `chore: reframe sase.sh around a two-post Agentic Software Engineering series`).
- All seven failing visual tests live in `tests/ace/tui/visual/test_ace_png_snapshots.py`; the rasterizer writes
  `expected.png`, `actual.png`, `diff.png`, and `summary.txt` per test under `.pytest_cache/sase-visual/…` which is what
  we'll inspect.

## Sequencing

The three fixes are independent. I'll do them in the order below because:

- (1) is a one-line shell command + commit, separate-repo blast radius, and unblocks the `bead-backend` job in
  isolation.
- (2) is contained to two files in this repo and unblocks `Deploy Docs` immediately.
- (3) requires per-snapshot human review and may surface a real regression we'd want to fix instead of accepting.

Doing (1) and (2) first means even if (3) takes longer, two of three workflows can go green on the next push.

---

## Step 1 — Sibling repo: rustfmt in `../sase-core`

**Where:** `/home/bryan/projects/github/sase-org/sase-core` (the sibling Rust core repo; see tier-3 memory
`memory/long/external_repos.md`).

**Files rustfmt wants to rewrite:**

- `crates/sase_core/src/notifications/mod.rs:6` — `pub use mobile::{…}` block
- `crates/sase_gateway/src/routes.rs:22` — `use sase_core::notifications::{…}` block

In both cases rustfmt is moving `mobile_notification_error_from_wire` onto its own line and keeping
`mobile_notification_priority_from_wire` paired with the next symbol (`pending_action_identity,` or
`ActionResultWire,`). No semantic change, no Python or wire impact.

**Actions:**

1. `cd ../sase-core && cargo fmt --all` (rewrites both files).
2. `cargo fmt --all -- --check` to confirm exit 0.
3. Optionally `cargo check --workspace` as a smoke test (cheap; rustfmt edits should never break compilation but
   verifies the workspace is healthy).
4. Commit with the sase commit skill (per memory, commits to sibling repos go through `sase commit`, never bare
   `git commit`). Message: `chore: apply rustfmt to notifications import blocks`.
5. Push.

**Cross-repo guard:** the `sase_sibling_commit_stop_hook` in this repo will block any commits **here** while `sase-core`
has uncommitted changes, so step 4 has to land before step 2/3 below.

**Verification:** next `bead-backend` run on this repo's CI should pass the `cargo fmt --all -- --check` step.

---

## Step 2 — This repo: Deploy Docs / PDF nav vs. blog plugin collision

**Where:** `/home/bryan/projects/github/sase-org/sase_102`

**Root cause recap:** the mkdocs-material `blog` plugin "consumes" `docs/blog/posts/*.md` and republishes them at
`/blog/<slug>/` (because `post_url_format: "{slug}"`). Listing them in `nav` triggers mkdocs's "included in the 'nav'
configuration, but this file is excluded from the built site" info message — mkdocs strips the nav entry but
`tools/postprocess_docs_pdf:_load_chapters` then can't find `site/blog/posts/<slug>/index.html` and aborts.

**Decision point — three viable approaches:**

| Option | Change                                                                                                                                | Pros                                                                   | Cons                                                                                                                                                                                                                                                                     |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| A      | Revert the two `blog/posts/...md` entries from `mkdocs.yml` `nav` (added in `6b7b26ad`)                                               | Smallest diff; restores green CI on the existing branch                | Walks back the user's intent in `6b7b26ad` to "expose both posts directly in the mkdocs Blog sidebar"                                                                                                                                                                    |
| B      | Change `post_url_format` to `"posts/{slug}"` so the blog plugin emits `site/blog/posts/<slug>/index.html` matching the nav references | Keeps posts visible in sidebar; fixes URL/file alignment in one stroke | mkdocs may still emit the "excluded from built site" warning (the plugin still owns the file regardless of URL). Need to test locally to confirm. Also changes existing post URLs (SEO impact if any external links exist — probably none yet since posts are days old). |
| C      | Teach `tools/postprocess_docs_pdf` to map blog-post nav entries to the blog plugin's actual emitted path (`blog/<slug>/`)             | Keeps both nav visibility and existing URL scheme                      | Couples the post-processor to mkdocs-material blog-plugin internals; brittle                                                                                                                                                                                             |

**Recommendation:** Try (B) first — it's a single-line config change and likely preserves the user's intent. If the
mkdocs strict build still rejects nav-listed blog posts even with the URL aligned, fall back to (A) and document the
"blog posts live in the blog plugin, not in nav" rule with a comment in `mkdocs.yml`. **Do not** pursue (C) without the
user weighing in — coupling a custom tool to plugin internals is a maintenance liability we shouldn't take on
unprompted.

**Files to inspect / edit:**

- `mkdocs.yml` lines 12–18 (the `nav` Blog section), line 94 (`post_url_format`).
- `mkdocs-pdf.yml` line 13 (also sets `post_url_format`).
- `tools/postprocess_docs_pdf` (read-only — only edit if both A and B prove infeasible).

**Actions:**

1. Locally run `just docs-pdf-check` once on the current state to confirm we reproduce the failure with the same error
   string. (This installs playwright + chromium; takes ~1 minute. Skip if hostile to a clean local env.)
2. Try option B: change `post_url_format: "{slug}"` to `post_url_format: "posts/{slug}"` in both `mkdocs.yml` and
   `mkdocs-pdf.yml`.
3. Re-run `just docs-pdf-check`. If it goes green, we're done. If mkdocs still emits the "excluded from built site"
   warning under `--strict`, abandon B and apply A instead (delete the two added nav lines), restore `post_url_format`,
   and lean on `blog/index.md` for discoverability.
4. Either way, also run `just docs-check` to make sure the non-PDF build still passes.

**Verification:** `just docs-pdf-check` exits 0 locally; Deploy Docs goes green on next push.

---

## Step 3 — This repo: visual PNG snapshot drift

**Where:** `/home/bryan/projects/github/sase-org/sase_102`

**Snapshots that changed (all in `tests/ace/tui/visual/snapshots/png/`):**

1. `changespec_initial_120x40.png`
2. `changespec_selected_row_120x40.png`
3. `query_edit_modal_120x40.png`
4. `agents_list_120x40.png`
5. `agents_selected_row_120x40.png`
6. `agents_unread_highlight_120x40.png`
7. `axe_selected_row_120x40.png`

These cover the changespec, agents, AXE and query-edit panels — the same surfaces touched by recent feature commits
(unread highlight extensions, chop run history cache changes). The 6.5% pixel diff on `changespec_initial_120x40` is
large but consistent with a layout/colour adjustment, not noise. Still, we must look before we update.

**Actions:**

1. `just install` (ephemeral workspace per `memory/short/workspaces.md`).
2. `just test-visual` to regenerate the per-test `.pytest_cache/sase-visual/<…>/{expected,actual,diff,summary}.png`
   artifacts on the local box.
3. For each of the 7 snapshots, open `expected.png` vs. `actual.png` vs. `diff.png` (the user can do this with their
   image viewer of choice). The user decides per-test:
   - **Intended change** → keep the new render and update the golden.
   - **Unintended regression** → fix the source code instead; don't update the golden.
4. Once the user has decided which goldens to bless, run `just test-visual -- --sase-update-visual-snapshots` (the flag
   wired up in `tests/ace/tui/visual/conftest.py`) to overwrite the goldens. (If only a subset should be updated, run it
   scoped to those test ids.)
5. Re-run `just test-visual` plain to confirm everything passes.
6. Stage only the snapshot PNGs that were intentionally updated
   (`git add tests/ace/tui/visual/snapshots/png/<file>.png`).

**Pause point:** Step 3 is the only step in this plan where I'll stop and ask you to look at the diff PNGs before I
touch the goldens. I will not run `--sase-update-visual-snapshots` unilaterally; blindly accepting a 6.5% pixel diff
would defeat the purpose of golden tests.

**Verification:** `just test-visual` exits 0; the `visual-test` and `test (3.14)` jobs go green on next push.

---

## Step 4 — Final repo-level verification (this repo)

After steps 1–3 land:

1. `cd /home/bryan/projects/github/sase-org/sase_102 && just install` (ephemeral workspace dep refresh).
2. `just check` — the build-and-run memory mandates this for any change in this repo, and it bundles `fmt-py-check`,
   `fmt-md-check`, ruff, mypy, pyvision, sdd-validate, and the full pytest run (which includes the visual suite).
3. `just docs-pdf-check` — not in `just check`, so run it separately to validate Deploy Docs.
4. From `../sase-core`: `just rust-check` — covers `rust-fmt-check`, `rust-clippy`, `rust-test`. Confirms the Step 1
   commit is clean and the workspace still builds.

If all four exit 0, push and watch CI go green. If anything red, surface the failure to the user with the exact error
rather than guessing at a deeper fix.

---

## Out of scope (intentional)

- **No refactor of `tools/postprocess_docs_pdf`** to be blog-plugin-aware (option C above) — too speculative without the
  user's input.
- **No reworking of `mkdocs.yml` blog plugin configuration** beyond the `post_url_format` toggle. The plugin is doing
  its job; we're aligning around it.
- **No re-recording of unrelated snapshots** — only the 7 failing ones, and only after per-snapshot review.
- **No CI workflow changes.** Failures are in the code/config under test, not the workflow definitions.
- **No `cargo clippy` fixes in sase-core** beyond what `cargo fmt` produces. Step 1 is rustfmt-only; clippy is green per
  the last successful runs.

## Risks and mitigations

- **Risk:** Option B (`post_url_format: "posts/{slug}"`) doesn't actually silence the "excluded from built site" warning
  under `--strict`. **Mitigation:** verify with a local `just docs-pdf-check` before committing; fall back to option A.
- **Risk:** A "diff" snapshot is actually a real regression (e.g., the chop history cache change broke a render).
  **Mitigation:** Step 3's pause point — user inspects diffs before any golden is overwritten.
- **Risk:** The `sase_sibling_commit_stop_hook` blocks commits in this repo while sase-core has staged changes.
  **Mitigation:** finish Step 1 (commit + push to sase-core) before committing Steps 2 or 3 here.
- **Risk:** Newer CI failures land while we work. **Mitigation:** rebase and re-check before pushing.
