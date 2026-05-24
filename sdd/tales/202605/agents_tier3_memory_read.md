---
create_time: 2026-05-23 20:54:11
status: done
---
# Plan: Agents Tier 3 Memory Read Instructions

## Goal

Update the root `AGENTS.md` instructions so agents know that Tier 3 long-term memory must be accessed through the
audited `sase memory read` command, using paths relative to `memory/`.

## Context

- `sase memory read` expects a path relative to `memory/`, for example `long/generated_skills.md`.
- The current Tier 3 section lists paths as `memory/long/generated_skills.md` and `memory/long/tui_jk_baseline.md`,
  which is not the argument shape the command expects.
- Dynamic memory cache files under `.sase/memory/` can already contain the corresponding long-term memory content; the
  existing dynamic-memory note should remain semantically intact so agents do not duplicate reads when the content was
  already injected.

## Implementation

1. Edit the root `AGENTS.md` Tier 3 section to say agents MUST use:

   ```bash
   sase memory read <long-memory-path> --reason "<why this context is needed>"
   ```

2. Make clear that `<long-memory-path>` is relative to `memory/`, and agents should not read canonical
   `memory/long/*.md` files directly.

3. Rename the Tier 3 entries from `memory/long/generated_skills.md` and `memory/long/tui_jk_baseline.md` to
   `long/generated_skills.md` and `long/tui_jk_baseline.md`.

4. Preserve the existing domain triggers and the Tier 2 dynamic-memory exception: if a `long-` dynamic memory file was
   already injected, agents do not need to separately read the corresponding Tier 3 file.

## Verification

- Review the edited `AGENTS.md` for consistency with `src/sase/main/parser_memory.py` and `src/sase/memory/read_log.py`.
- Run the repo-required check after file changes: `just install`, then `just check`, unless the command is blocked by
  environment issues.
