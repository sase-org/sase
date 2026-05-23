---
create_time: 2026-05-23 10:11:34
status: done
prompt: sdd/prompts/202605/init_memory_sibling_reads_writes.md
---
# Plan: Clarify Sibling Repository Memory Wording

## Goal

Update the generated SASE memory produced by `sase memory init` and the compatibility alias `sase init memory` so the
sibling repository instructions cover both reviewing code and making file changes in sibling repositories.

The generated text should use:

```text
When you need to make changes to files in a sibling repository or need to review sibling repository code, agents MUST run:
```

It should also replace the phrase `sibling edits` with `sibling reads/writes`.

## Scope

This is a Python CLI memory-rendering change. It stays in the existing `init_memory` rendering path and does not cross
the Rust core backend boundary because it only affects generated Markdown text.

The source of truth is `src/sase/main/init_memory/roots.py`, specifically the sibling repository section rendered into
`memory/short/sase.md` for project and home memory roots.

## Implementation

1. Update `_extend_sibling_repository_section()` in `src/sase/main/init_memory/roots.py`:
   - Replace the existing trigger sentence with the requested longer sentence.
   - Replace the final path-use phrase so it ends with `sibling reads/writes`.

2. Add or tighten focused regression assertions in `tests/main/test_init_memory_handler.py`:
   - Verify generated project memory contains the new trigger sentence.
   - Verify generated memory contains `sibling reads/writes`.
   - Verify the old phrases are absent, so future edits cannot accidentally restore the narrower wording.

3. Do not hand-edit checked-in memory files as part of the source patch. The repo instructions say memory files require
   approval before modification, and the command source plus regression tests are enough to prove future generated
   output.

## Verification

Run focused tests first:

```bash
.venv/bin/python -m pytest tests/main/test_init_memory_handler.py
```

Because source files changed in this repo, run the repo-required final check:

```bash
just install
just check
```

Do not run `sase init memory` or `sase memory init` against this working repo unless the user explicitly approves
refreshing the generated memory files, since that would modify memory files and may trigger generated-memory deployment
behavior.
