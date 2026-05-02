---
create_time: 2026-04-13 11:09:39
status: done
prompt: sdd/prompts/202604/migrate.md
---

# Plan: Migrate Tier 2 Xprompts to Long-Term Memory

## Context

Commit `fa4bf824d86d` introduced a mechanism where Markdown files in `memory/long/` are auto-discovered as dynamic
memory xprompts (Tier 2 memory) if they contain a `keywords` field in their YAML frontmatter. This eliminates the need
for separate `.md` xprompts in `~/xprompts/` and `content: "$(cat ...)"` substitutions.

## Objective

Migrate the four existing tier 2 xprompts (`buganizer.md`, `build_cleaner.md`, `golinks.md`, `screenshots.md`) from
`~/xprompts/` to `~/.gemini/memory/long/`, adapting their frontmatter, and update `~/.gemini/GEMINI.md` to reference
them.

## Implementation Steps

1. **Migrate `buganizer.md`**:
   - Create `~/.gemini/memory/long/buganizer.md`.
   - Set YAML frontmatter to:
     ```yaml
     ---
     keywords: [buganizer, bug, b/, issue]
     ---
     ```
   - Copy the content from `~/xprompts/buganizer.md`.
   - Delete `~/xprompts/buganizer.md`.

2. **Migrate `build_cleaner.md`**:
   - Create `~/.gemini/memory/long/build_cleaner.md`.
   - Set YAML frontmatter to:
     ```yaml
     ---
     keywords: [build, BUILD, dependency, build_cleaner]
     ---
     ```
   - Copy the content from `~/xprompts/build_cleaner.md`.
   - Delete `~/xprompts/build_cleaner.md`.

3. **Migrate `screenshots.md`**:
   - Create `~/.gemini/memory/long/screenshots.md`.
   - Set YAML frontmatter to:
     ```yaml
     ---
     keywords: [screenshot, snapit, image]
     ---
     ```
   - Copy the content from `~/xprompts/screenshots.md`.
   - Delete `~/xprompts/screenshots.md`.

4. **Merge `golinks.md` into `golinks_reference.md`**:
   - Update `~/.gemini/memory/long/golinks_reference.md` to include YAML frontmatter:
     ```yaml
     ---
     keywords: [golink, go/, goctl]
     ---
     ```
   - Copy the "Common commands" section from `~/xprompts/golinks.md` into `golinks_reference.md`.
   - Delete `~/xprompts/golinks.md`.

5. **Update `~/.gemini/GEMINI.md`**:
   - Update the "Tier 3 (long-term) Memory" section to list and describe the newly migrated files (`buganizer.md`,
     `build_cleaner.md`, `screenshots.md`).
   - Remove any specific references to creating or storing files in `~/xprompts/` if it mentions it, as Tier 2 memory is
     now just the keyword-tagged Tier 3 memory.

6. **Version Control**:
   - Add all modified and new files to the `~/.gemini` git repository.
   - Commit the changes with an appropriate commit message.
