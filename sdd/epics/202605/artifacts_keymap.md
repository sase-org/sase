---
create_time: 2026-05-07 21:43:39
status: done
prompt: sdd/prompts/202605/artifacts_keymap.md
bead_id: sase-2c
tier: epic
---
# Generalize Agents Tab Artifact Viewing

## Context

The current Agents tab has a `V` / `view_image` action that only opens the image currently visible in the file panel via
`kitten icat`. Done agents already surface some attachments through `done.json`: `plan_path`, generated
`markdown_pdf_paths`, and `image_paths`. Chat transcripts are stored separately under `~/.sase/chats/` and are usually
reachable through `done.json["response_path"]` or `agent_meta.json["chat_path"]`.

The requested product shape is broader:

- change the Agents tab action from `V` / "view image" to `A` / "artifacts";
- every done agent should have at least one artifact, its chat transcript;
- plan files and image files added/modified by the agent should be artifacts;
- explicit `sase artifact create` artifacts should be moved to `~/.sase/artifacts/` and remain associated with the agent
  even after dismissal and later revive;
- markdown artifacts should be viewed as rendered PDFs converted to PNG pages with
  `pdftoppm -png <pdf_path> <png_path_prefix>`, then displayed page-by-page with `kitten icat`;
- when there is one artifact, open it directly; when there are multiple, show an artifact selection panel with
  single-key choices;
- show artifact entries in a new `ARTIFACTS` field in the selected agent metadata panel.

The work crosses the Python/Rust backend boundary because artifact association and lookup should not become TUI-private
behavior. The Python TUI may own presentation and key handling, but artifact indexing/discovery should be reusable by
CLI and future integrations.

One important binding conflict exists today: `A` is currently the app-level `show_agent_run_log` binding. The least
surprising migration is to make `A` the Agents-tab artifact action and move the direct run-log binding to `V` (run log
can also remain in the command palette and leader-mode affordances). This avoids duplicate Textual app bindings while
keeping a primary key for the displaced command.

## Phase 1: Define the Artifact Domain and Persistent Index

Owner: backend/core agent.

Implement a small artifact model and persistence layer that can be used by both the TUI and CLI.

- Add an `AgentArtifact` / wire-equivalent model with fields like `id`, `label`, `kind` (`chat`, `plan`, `image`,
  `markdown`, `pdf`, `file`), `path`, `source_path`, `created_at`, and stable agent association fields
  (`agent_artifacts_dir`, project, raw timestamp, agent name when known).
- Store explicit artifacts under `~/.sase/artifacts/`, using a stable per-agent subdirectory or collision-resistant file
  names. Use atomic writes and a lock for the index.
- Store association data outside the per-run artifact directory so dismissal cannot erase it. A JSONL or SQLite index
  under `~/.sase/artifacts/` is acceptable; choose whichever best fits existing core patterns.
- Add read APIs that merge default artifacts from existing run metadata with explicit artifacts from the persistent
  index:
  - chat transcript from `done.json["response_path"]` or `agent_meta.json["chat_path"]`;
  - plan files from `done.json["plan_path"]`, `agent_meta.plan_path`, `agent_meta.sdd_plan_path`, and `plan_path.json`;
  - image paths from `done.json["image_paths"]`;
  - explicit rows created by `sase artifact create`.
- Deduplicate by resolved path while preserving stable display order: chat, plans, explicit artifacts, images/other
  generated attachments.
- If this lands in `../sase-core`, update the Rust wire/API and Python facade in this repo in the same phase. If the
  implementation stays Python-only initially, keep it behind a thin facade so it can migrate later without TUI churn.

Tests:

- unit tests for explicit index create/read/dedupe;
- dismissal/revive-style tests proving explicit artifact associations survive when per-agent marker files are removed
  and restored;
- scanner/facade tests for default chat/plan/image artifact synthesis from existing `done.json` and `agent_meta.json`.

## Phase 2: Add `sase artifact create` and the `/sase_artifact` Skill Source

Owner: CLI/skills agent.

Add the command agents will call when instructed to create a SASE artifact.

- Register a new top-level `artifact` command with a `create` subcommand.
- Follow repo CLI conventions: every argument needs a short option. Suggested interface:
  `sase artifact create -p <path> [-n <label>] [-k <kind>]`.
- Require `SASE_AGENT=1` and `SASE_ARTIFACTS_DIR`; fail clearly outside an agent.
- Validate the source file exists, move it into `~/.sase/artifacts/`, create/update the persistent association, and
  print the stored path/id.
- Update any artifact index row with enough context from env and `agent_meta.json` to survive later lookup by the TUI.
- Add `src/sase/xprompts/skills/sase_artifact.md` as the source skill file, not a generated provider-specific
  `SKILL.md`. The skill should instruct agents to create the requested file, then run `sase artifact create`.
- Update skill discovery/generation tests and run `sase init-skills --force` only if this phase is expected to deploy
  generated skills in the workspace. Do not hand-edit live provider skill files.

Tests:

- parser tests for `artifact create`;
- handler tests for missing env, missing file, move behavior, short options, and index association;
- source-skill discovery tests proving `/sase_artifact` is packaged and rendered.

## Phase 3: Build Artifact Rendering and Viewer Primitives

Owner: viewer/rendering agent.

Replace the image-only viewer with artifact-aware rendering helpers that remain independent of Textual widgets.

- Keep existing image support but rename APIs from `view_image_file` toward artifact/page semantics. Leave a
  compatibility wrapper only if needed by notification modals.
- Add markdown-to-PDF handling by reusing `sase.attachments.markdown_pdf.render_markdown_pdf` where possible. Render
  transient PDFs into a cache/temp directory rather than polluting agent workspaces.
- Add PDF-to-PNG conversion using exactly `pdftoppm -png <pdf_path> <png_path_prefix>` semantics. Collect generated page
  files in numeric page order.
- Add an interactive `kitten icat` page loop:
  - image artifacts: one page, `q` returns;
  - markdown/PDF artifacts: `n` next, `p` previous, `q` quit;
  - clear or redraw between pages so old pages do not visually stack.
- Validate dependencies up front and return structured warnings for missing `kitten`, `pdftoppm`, `pandoc`, or PDF
  engines.
- Keep all terminal display under the caller's `self.suspend()` context.

Tests:

- unit tests with mocked `subprocess.run` for `pdftoppm` output ordering;
- viewer loop tests using a mocked key input path or extracted pure state machine;
- existing image tests updated from "V" wording to "A"/artifact wording;
- failure tests for missing tools and unsupported artifact kinds.

## Phase 4: Agents Tab TUI Integration

Owner: TUI agent.

Wire the artifact model/viewer into `sase ace` without broad display rewrites.

- Rename the app action from `view_image` to `view_artifact` or `open_agent_artifacts`.
- Default keymaps:
  - set artifact action to `A`;
  - move direct `show_agent_run_log` to `V` or remove its primary binding if the command-palette/leader path is deemed
    enough;
  - update `src/sase/default_config.yml`, `src/sase/ace/tui/bindings.py`, keymap metadata, command catalog, footer, and
    help modal text together.
- Compute available artifacts for the selected done agent through the Phase 1 facade.
- Behavior:
  - no selected agent: warn;
  - selected running agent with no completed artifacts: warn or only show explicit artifacts if any exist;
  - one artifact: open it immediately;
  - multiple artifacts: push a new artifact selection modal/panel where each entry has a single-key selector.
- Do not base artifact availability only on the currently visible file panel. Image artifacts must be selectable even if
  they are not the current file-panel file.
- Remove the old attempt-view fallback from the artifact key; keep attempt history on `D`.
- Add an `ARTIFACTS` field to the agent metadata header. Keep the cheap j/k immediate header disk-free; populate
  artifacts only on the full update path.

Tests:

- TUI action tests for one artifact direct-open, multiple artifact modal, no artifacts warning, and suspend behavior;
- keymap/config/help/footer tests updated for `A` artifacts and the displaced run-log binding;
- metadata header tests for `ARTIFACTS` display and cheap-header omission.

## Phase 5: Artifact Selection Panel Polish

Owner: TUI/modal polish agent.

Make the selection panel usable and consistent with existing keyboard-first modals.

- Reuse existing modal patterns (`OptionListNavigationMixin` or similar) where appropriate.
- Display artifact label, kind, short path, and a clear single-key selector.
- Support more than nine artifacts with a sensible key set (`1-9`, `0`, then letters excluding global quit keys) or a
  fallback searchable/navigable list if the existing modal patterns already solve this.
- `q`/Escape should return to the TUI without opening anything.
- Opening an artifact should suspend the TUI, run the Phase 3 viewer, then return to the same selected agent.
- Ensure the footer/help language does not imply only images.

Tests:

- modal key selection tests;
- ordering and truncation tests for long paths/labels;
- regression tests for returning focus to the Agents tab.

## Phase 6: End-to-End Validation and Documentation

Owner: integration agent.

Validate the full workflow and close gaps.

- Create fixture done agents with:
  - only a chat transcript;
  - chat + plan markdown;
  - chat + image;
  - chat + explicit `sase artifact create` artifact;
  - dismissed then revived explicit artifact association.
- Run focused tests first, then `just install` if needed and `just check` before final handoff.
- Manually smoke-test in `sase ace` where possible:
  - `A` on single-artifact done agent opens the chat transcript rendered as pages;
  - `A` on multi-artifact done agent opens the artifact panel;
  - `n`/`p`/`q` work in the PNG page viewer;
  - image artifacts still open directly via `kitten icat`;
  - metadata panel shows `ARTIFACTS`.
- Update user-facing docs/help strings only where they already exist; avoid adding a broad new documentation page unless
  tests or established help content require it.

## Open Decisions for Implementers

- Whether artifact persistence should land immediately in Rust core or in a Python facade shaped for later migration.
  The boundary guidance points toward core because CLI and TUI need shared behavior.
- Whether `show_agent_run_log` should move to `V` or become command-palette/leader-only. The plan assumes `V` to keep a
  direct binding and avoid a duplicate `A`.
- Whether generated markdown PDFs should be cached across opens. A temp directory is simpler; a content-hash cache under
  `~/.sase/artifacts/render_cache/` is better if large chat transcripts make repeated opens slow.
