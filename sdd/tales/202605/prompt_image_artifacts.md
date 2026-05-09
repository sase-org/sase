---
create_time: 2026-05-09 04:05:45
status: done
prompt: sdd/prompts/202605/prompt_image_artifacts.md
---
# Plan: Prompt Image References as Agent Artifacts

## Goal

Make image file paths referenced in an agent prompt appear as `ARTIFACTS` entries in the Agents tab metadata panel and
make those same images openable from the `A` artifacts modal. The motivating case is a Telegram-launched prompt
containing a saved image path such as `/home/bryan/.sase/telegram/images/20260509_080052_AgACAgEAAxkB.jpg`.

## Current Behavior

- The `A` keypath calls `list_agent_artifacts()` from `sase.core.agent_artifact_facade`.
- `list_agent_artifacts()` currently synthesizes default artifacts from `done.json` and `agent_meta.json`, including
  `done.json.image_paths`.
- The Agents metadata panel uses `append_agent_artifacts_section()` and currently shows the selected plan plus explicit
  user artifacts, but intentionally omits default chat/image artifacts.
- Telegram image paths can appear only inside prompt text (`raw_xprompt.md` / `*_prompt.md`) and are not necessarily
  written to `done.json.image_paths`, especially while the agent is still running.

## Proposed Design

1. Add shared prompt-image discovery to the core artifact synthesis path.
   - Read prompt-bearing files in the agent artifacts directory, starting with `raw_xprompt.md` and any `*_prompt.md`
     files.
   - Extract path-like tokens whose suffix is a supported image type (`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.bmp`,
     `.tif`, `.tiff`).
   - Support absolute paths, `~` paths, and workspace-relative paths when `workspace_dir` is known from `done.json` or
     `agent_meta.json`.
   - Prefer existing files to avoid turning prose into dead artifacts.

2. Make discovered prompt images part of `synthesize_default_agent_artifacts()`.
   - Keep existing `done.json.image_paths` behavior.
   - Append prompt-discovered image artifacts after explicit `image_paths`, deduping by resolved path through the
     existing `dedupe_artifacts()` helper.
   - Use `kind="image"` so the existing artifact viewer opens the image renderer without a TUI-specific special case.

3. Update the Agents metadata `ARTIFACTS` section to use the same artifact list.
   - Replace the local “plan plus explicit only” collection with `list_agent_artifacts()`.
   - Filter out chat transcripts so the metadata panel remains focused on user-relevant file artifacts.
   - Include image artifacts, including prompt-discovered images, so the header and `A` modal agree.

4. Add focused tests.
   - Core test: a prompt containing an absolute `.jpg` path produces an `image` artifact even without
     `done.json.image_paths`.
   - Core test: workspace-relative image paths resolve using `workspace_dir`.
   - Header test: `ARTIFACTS` includes default image artifacts and prompt-discovered images while still omitting chat
     transcripts.
   - Existing modal/viewer tests should continue to pass because they consume `AgentArtifact(kind="image")`.

5. Verify.
   - Run the focused artifact/header tests first.
   - Run `just install` if needed, then `just check` as required by repo instructions after code changes.

## Risks and Mitigations

- Regex false positives: restrict extraction to recognized image suffixes and require the resolved path to be an
  existing file.
- Prompt file read cost: this path is only used in the full, non-cheap metadata refresh and artifact modal action; keep
  reads bounded to known prompt files in one artifact directory.
- Duplicates across `done.json.image_paths` and prompt references: use existing resolved-path dedupe behavior.
