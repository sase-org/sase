---
create_time: 2026-05-04 17:16:49
status: done
prompt: sdd/prompts/202605/default_xprompts_dir.md
---
# Default XPrompts Directory

## Context

The package default config lives at `src/sase/default_config.yml`. Today, built-in file-backed xprompts are loaded from
`src/sase/xprompts/*.md`, while project-local xprompts are loaded from CWD `xprompts/*.md` and are namespaced when a
project is detected.

The current `research_swarm` prompt lives in the repo-root `xprompts/research_swarm.md`. In this repo that makes it a
project-local xprompt rather than a package default. The requested behavior is to introduce a new package resource
directory, `src/sase/default_xprompts/`, beside `default_config.yml`; every markdown file in that directory should be
available as a built-in xprompt.

## Goals

1. Add `src/sase/default_xprompts/` as a built-in markdown xprompt source.
2. Move `research_swarm.md` from repo-root `xprompts/` into the new package directory.
3. Keep built-in default xprompts global, not project-namespaced.
4. Preserve existing override behavior: project, user, and config xprompts can still override built-ins.
5. Update user-facing source classification and docs so the new source is visible and understandable.
6. Add focused regression coverage for discovery, source attribution, and non-namespacing.

## Non-Goals

- Do not move YAML workflows into `default_xprompts/`; the request only covers markdown files.
- Do not rename existing built-in workflow/skill resources under `src/sase/xprompts/`.
- Do not change xprompt argument parsing, multi-agent splitting, or workflow execution behavior.
- Do not alter the content of `research_swarm.md` except for the path move.

## Design

Add a loader helper for `src/sase/default_xprompts/`, resolved with `importlib.resources.files("sase")` in the same
style as `default_config.yml` and `src/sase/xprompts/`. The helper should scan only top-level `*.md` files and reuse
`_load_xprompt_from_file()` so front matter, typed inputs, tags, snippets, skills, descriptions, and keywords keep the
same semantics as other markdown xprompts.

Integrate this source at the built-in/default layer of `get_all_xprompts()`. It should be loaded before user-visible
override layers, so normal project and user definitions still win on name conflict. Since these files are package
defaults, they should not be passed through `_namespace_xprompt()`.

Keep source attribution as the actual package file path. That matches existing file-backed built-ins and lets the TUI
open/read the source directly. Update catalog and TUI classification to treat paths under both `src/sase/xprompts/` and
`src/sase/default_xprompts/` as built-in.

## Implementation Plan

1. Add loader support.
   - Add `get_sase_package_default_xprompts_dir()` in `src/sase/xprompt/loader.py`.
   - Add `_load_xprompts_from_default_files()` that scans `*.md` under that directory.
   - Include its result in `get_all_xprompts()` at the built-in layer, before higher-priority user/project sources.
   - Update docstrings/comments that enumerate xprompt precedence.

2. Move the prompt.
   - Create `src/sase/default_xprompts/research_swarm.md`.
   - Move the exact content from `xprompts/research_swarm.md`.
   - Remove the old repo-root `xprompts/research_swarm.md` so it is no longer project-local.

3. Update UI/catalog source handling.
   - Teach `src/sase/xprompt/catalog.py` that package `default_xprompts/` paths are built-in.
   - Teach `src/sase/ace/tui/modals/xprompt_browser_helpers.py` to classify and resolve the new built-in path cleanly.
   - Add the new built-in directory to the xprompt location modal if the modal exposes built-in editable locations.

4. Update docs.
   - Update discovery-order docs in `docs/configuration.md` and `docs/xprompt.md` to mention
     `<sase_package>/default_xprompts/*.md`.
   - Add `#research_swarm` to the built-in xprompt list in `docs/xprompt.md`.
   - Keep docs scoped to markdown xprompts only.

5. Add tests.
   - Add or extend loader tests proving `research_swarm` is loaded from `default_xprompts`.
   - Assert it remains named `research_swarm` even when a project is provided/detected.
   - Assert the old CWD `xprompts/` source is not required for it to load.
   - Add a catalog/source classification test for `default_xprompts/`.

6. Verification.
   - Run `just install` first, per workspace memory.
   - Run focused xprompt loader/catalog tests.
   - Run `just check` before reporting completion.

## Risks And Mitigations

- **Precedence ambiguity:** Existing code separates package `xprompts/` files and `default_config.yml` entries. The new
  directory should behave as a default source, so tests will assert user/project file sources can still override the
  built-in `research_swarm`.
- **Packaging resource drift:** Because the directory sits inside `src/sase/`, hatchling should package it with the
  Python package. Verification should use `importlib.resources` rather than hardcoded source-tree paths.
- **TUI source labeling gap:** Runtime discovery could work while the browser labels the source as `Other`. Updating
  classification and adding a targeted test avoids that mismatch.

## Acceptance Criteria

- `src/sase/default_xprompts/research_swarm.md` exists with the current prompt content.
- `xprompts/research_swarm.md` no longer exists.
- `get_all_xprompts(project="sase")["research_swarm"]` resolves as a built-in, non-namespaced xprompt.
- Docs and xprompt browser/catalog source classification recognize `default_xprompts/` as built-in.
- Focused tests pass and `just check` passes.
