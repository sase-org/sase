---
create_time: 2026-05-09 21:17:34
status: done
prompt: sdd/prompts/202605/readme_docs_gap_coverage.md
---
# README Docs Gap Coverage Plan

## Context

The README reduction removed long-form reference material from the repository front door. The expanded acknowledgements
were already restored to `docs/acknowledgements.md`, but several other removed sections are not represented as
first-class docs pages.

I compared the pre-reduction README from `8613ef38^:README.md` against the current `README.md`, `docs/`, and
`mkdocs.yml`. Much of the removed material is already covered elsewhere:

- Core concept details exist in `docs/change_spec.md`, `docs/workflow_spec.md`, `docs/xprompt.md`, `docs/workspace.md`,
  `docs/sdd.md`, `docs/beads.md`, `docs/mobile_gateway.md`, and `docs/agent_images.md`.
- Feature-specific references exist for ACE, Axe, mentors, telemetry, LLM providers, VCS providers, plugins,
  notifications, and integrations.
- The acknowledgements section has already been recovered in `docs/acknowledgements.md`.
- The compact README still covers supported agents, quick start, development commands, Rust core requirements, and
  top-level links.

The remaining gaps are:

1. The old README's complete CLI command map no longer has a focused docs home. `docs/configuration.md` documents many
   flags, and subsystem pages document their own commands, but there is no command index that helps users discover the
   top-level `sase` surface.
2. The old README's project/source structure overview is not covered by a contributor-oriented docs page. Some subsystem
   pages contain local "Source Layout" tables, but there is no single orientation page for the repository layout.
3. The old README's docs build/deploy notes are not currently represented in docs. The README mentions `just docs-check`
   and `just docs-pdf-check`, but the production deployment workflow, strict-build expectations, and handbook PDF
   validation details were removed from the docs surface.
4. The old README's architecture/orientation material is only partially represented. `docs/index.md` now has strong
   product overview content and diagrams, but it does not include a concise textual system map that ties CLI, ACE, Axe,
   workflows, providers, plugins, and the Rust core together for readers who need implementation orientation.

## Proposed Changes

1. Add `docs/cli.md`

   Create a focused command index for the current `sase` CLI. This should be a navigational reference, not a duplicate
   of every detailed flag table. It should group commands by workflow:
   - Daily operation: `sase ace`, `sase run`, `sase agents ...`, `sase notify ...`
   - Work tracking and planning: `sase changespec ...`, `sase sdd ...`, `sase bead ...`
   - Automation: `sase axe ...`
   - Prompt/workflow authoring: `sase xprompt ...`, `sase lsp`, editor/file helper commands
   - Review and delivery: `sase commit`, `sase revert`, `sase restore`
   - Operations and diagnostics: telemetry, logs, config, path, core health, artifact creation, plan/questions

   Link each command group to the detailed docs page that owns the deeper reference. Derive wording from current docs
   and CLI surfaces rather than blindly restoring the old README table.

2. Add `docs/development.md`

   Create a contributor/developer orientation page that covers:
   - Setup and verification commands already preserved in README, plus the removed note that test selectors are
     normalized from the `just` invocation directory.
   - The required Rust core dependency and where to read more.
   - A concise repository source map derived from the old README's project structure, kept high-level enough to remain
     maintainable.
   - Documentation workflows: `just docs-check`, `just docs-pdf-check`, MkDocs site location, handbook PDF validation,
     and the checked-in Cloudflare Worker deployment path via `.github/workflows/docs-deploy.yml` and `wrangler.jsonc`.

   This should avoid repeating every file-level path from the old README; the goal is orientation, not an exhaustive
   tree dump.

3. Add `docs/architecture.md`

   Create a concise implementation architecture page that recovers the useful parts of the old architecture section
   while aligning it with current docs:
   - The system boundary: CLI, ACE TUI, Axe daemon, xprompt/workflow engine, ChangeSpecs/SDD/beads, provider layers,
     plugins, and the required Rust core.
   - How agent launches flow from prompt references through workspace resolution, provider invocation, artifacts,
     notifications, and review/commit workflows.
   - Where provider abstractions live and which detailed pages to read next.

   Reuse existing diagrams from `docs/images/` where appropriate instead of reintroducing a large ASCII diagram.

4. Update navigation and landing links

   Add the new pages to `mkdocs.yml` in appropriate sections:
   - `Architecture` under `Concepts`
   - `CLI Reference` under `Reference`
   - `Development` under `Reference` or a small contributor-oriented group if the current nav shape fits better

   Add lightweight cross-links from `docs/index.md` so readers can discover the command index, architecture overview,
   and contributor guide from the docs home.

## Verification

After implementation:

1. Run `just install` first for this ephemeral workspace.
2. Run Markdown formatting if needed.
3. Run `just check`.
4. Run `just docs-check` because the work changes MkDocs navigation and internal links.
5. Run `just docs-pdf-check` if the docs build changes materially affect the handbook output or if `docs-check` reveals
   generated-site issues that could affect the PDF.

## Non-goals

- Do not expand the README again.
- Do not restore stale or overly detailed command tables verbatim when current subsystem docs are more accurate.
- Do not duplicate the full acknowledgements content outside `docs/acknowledgements.md`.
- Do not change code behavior.
