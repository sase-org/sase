---
create_time: 2026-05-23 10:01:47
status: done
prompt: sdd/prompts/202605/memory_list_home_context.md
---
# Plan: `sase memory list` Loaded Context Accuracy

## Goal

Make `sase memory list` reflect the files that actually enter every agent launch context:

- Count the relevant `AGENTS.md` instruction files in loaded line and token totals.
- Show project `AGENTS.md`, home `~/AGENTS.md`, project memory files, and home `~/memory/**.md` files in the inventory.
- Preserve the existing distinction between loaded `@...` references, plain referenced-only memory paths, available
  memory files, and missing memory references.

## Product Semantics

The command should describe the current launch context, not just the current project memory directory.

Project context comes from the current working directory. Home context comes from `Path.home()`, because those files are
loaded regardless of the directory an agent is launched from. If the current project root is the home directory, the
home root must not be counted twice.

`AGENTS.md` files are instruction files rather than memory files, but their contents are loaded and therefore belong in
the loaded line/token totals. Provider shim files such as `CLAUDE.md`, `GEMINI.md`, `QWEN.md`, and `OPENCODE.md` should
remain visible as instruction roots but should not inflate loaded totals as if every provider shim were simultaneously
loaded.

## Implementation Shape

Extend the memory inventory model so `sase memory list` can combine multiple context roots:

- Keep current project-root behavior for existing project memory discovery.
- Add an optional home root to the list-command inventory path.
- Represent loaded instruction files explicitly enough to render and count `AGENTS.md`.
- Resolve `@memory/...` and plain `memory/...` references relative to the root that owns the source file, so project and
  home memory trees stay independent.
- Deduplicate by resolved path so shared paths or `cwd == home` do not double-count.
- Use display paths that make origin clear: project-relative paths for project files and `~/...` for home files.

Avoid changing `sase memory init` reachability validation unless a shared helper must be refactored; its current
compatibility rules are narrower and should remain stable.

## Rendering

Update the dashboard so it remains understandable with multiple roots:

- Summary should still show the current directory and project name.
- Instruction roots should include both project and home roots in a concise form.
- Loaded file, line, and token counts should include loaded memory files plus loaded `AGENTS.md` files.
- The entries table should include loaded `AGENTS.md` rows and home memory rows.
- Reference details should show `~/AGENTS.md -> @memory/...` for home references and project-relative paths for project
  references.
- Notes should clarify that `AGENTS.md` is counted because it is loaded instruction context, while plain memory paths
  remain referenced-only.

## Tests

Add focused tests around the inventory and renderer:

- Project `AGENTS.md` contributes to loaded line/token totals and appears in the output.
- Home `~/AGENTS.md` and `~/memory/short/*.md` are included when a home root is provided.
- Project and home memory files with the same relative path are both shown with unambiguous display paths.
- `cwd == home` avoids duplicate entries and duplicate loaded counts.
- Existing plain-reference and init-memory reachability behavior remains unchanged.

## Verification

Run targeted tests first:

```bash
.venv/bin/python -m pytest tests/test_memory_inventory.py tests/main/test_memory_handler.py
```

Because this repo requires it after file changes, run:

```bash
just install
just check
```

Then run `sase memory list` from the repo and inspect that the summary loaded-line total includes project/home
`AGENTS.md` and that home paths are visible as `~/...`.
