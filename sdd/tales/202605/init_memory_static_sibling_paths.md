---
create_time: 2026-05-23 10:23:29
status: done
prompt: sdd/prompts/202605/init_memory_static_sibling_paths.md
---
# Plan: Conditional Sibling Workspace Instructions in `sase init memory`

## Goal

Update `sase memory init` and its `sase init memory` alias so generated `memory/short/sase.md` only tells agents to run
`sase workspace open` when the source `sase.yml` has at least one configured sibling repository whose
`workspace.strategy` is not `none`.

For sibling repositories that do use `workspace.strategy: none`, generated memory should explicitly list them as static
path siblings and include the path agents should use for each one, so agents do not incorrectly look for a numbered
workspace checkout.

## Current Behavior

`src/sase/main/init_memory/roots.py` always renders the `sase workspace open -p <sibling_repo> <workspace_num>` block
for the sibling repository section, including when there are no siblings and when every sibling should use a static
path.

`src/sase/main/init_memory/config.py` currently parses sibling entries only far enough to capture `name` and
`description`; it discards `path` and `workspace.strategy`, so the renderer cannot distinguish numbered-workspace
siblings from static-path siblings.

## Design

1. Extend the memory-only sibling model.
   - Add `path`, `workspace_strategy`, and a rendered static path field to `SiblingMemoryEntry`.
   - Treat missing or empty `workspace.strategy` the same way runtime sibling resolution does: default to `suffix`.
   - Treat `workspace.strategy: none` as the static-path case.

2. Resolve static paths before rendering.
   - Require `sibling_repos[].path` during memory generation, matching the public schema.
   - Expand `~` and environment variables.
   - Resolve relative paths from the project primary checkout when possible, matching the sibling repo resolution
     contract that relative sibling paths are based on the primary workspace rather than the numbered workspace.
   - Prefer the managed checkout marker's `primary_workspace_dir`; fall back to the current project root, with a
     conservative adjacent-workspace suffix fallback when available.

3. Render the sibling section by strategy.
   - Keep the existing configured sibling summary list.
   - If any entries have `workspace.strategy: none`, add a short static-path list with one bullet per static sibling:
     sibling name plus the path agents should use.
   - If any entries are not `none`, render the `sase workspace open` command block and make it clear that the command is
     for numbered-workspace siblings.
   - If there are no numbered-workspace siblings, omit the command block entirely.

4. Keep project and home memory behavior parallel.
   - Project memory uses project-local `./sase.yml`.
   - Home memory uses the configured global `sase.yml` source.
   - Each generated memory file bases the conditional instructions on the sibling entries from the `sase.yml` file that
     produced that memory target.

## Tests

Add focused coverage in `tests/main/test_init_memory_handler.py`:

- No sibling repos means no `sase workspace open` command is generated.
- A config where all siblings use `workspace.strategy: none` lists each static sibling and its resolved path, and does
  not render the `sase workspace open` command.
- A mixed config renders both the static-path list and the numbered-workspace command block, with wording that makes the
  split clear.
- Relative static sibling paths resolve from the primary checkout instead of a numbered workspace when a managed
  checkout marker is present.
- Existing project-vs-home sibling source behavior still passes.

## Documentation

Update the initialization documentation to state that generated memory distinguishes static-path siblings from
numbered-workspace siblings and only includes `sase workspace open` instructions when at least one configured sibling
uses numbered workspace resolution.

## Verification

Run the targeted memory-init tests first:

```bash
python -m pytest tests/main/test_init_memory_handler.py
```

Because this changes source files in the SASE repo, run the required repository check before finishing:

```bash
just install
just check
```

Do not run `sase init memory` against this working repo unless explicitly approved, because repository instructions say
memory files must not be modified without user approval.
