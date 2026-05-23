---
create_time: 2026-05-23 11:25:21
status: done
prompt: sdd/prompts/202605/static_sibling_memory_display.md
---
# Plan: Inline Static Sibling Paths in Generated Memory

## Context

`sase init --check` currently reports drift for `~/.local/share/chezmoi/home/memory/short/sase.md`. The chezmoi repo
commit `1258e3724b49` changed that generated file from a two-part static sibling display:

- sibling description in the normal sibling list
- separate `Static-path sibling repositories...` section with an absolute resolved path

to a single sibling list item that keeps the description and appends a concise location sentence:

```markdown
- `chezmoi`: Chezmoi-managed dotfiles and global SASE configuration source. This repo is defined in the
  `~/.local/share/chezmoi/` directory.
```

The implementation should make the generator produce that content from the existing global `sase.yml` entry without
modifying the memory file directly.

## Approach

1. Update the memory init sibling renderer so `workspace.strategy: none` entries no longer create a separate static-path
   section.
2. Render each static sibling as a normal sibling list item whose description is followed by
   `This repo is defined in the `<path>/` directory.`
3. Use the configured path for display, preserving user-facing shorthand such as `~`, and normalize only the display
   shape enough to make directory paths consistently end in `/`.
4. Keep numbered-workspace siblings unchanged: they should still render the `sase workspace open -p ...` instructions
   whenever at least one non-static sibling is present.
5. Keep the existing resolved static path field in the config model if it is still useful for validation or future
   behavior, but do not surface it in the generated prose.

## Tests

1. Update focused `sase memory init` tests for static-only siblings to assert inline path prose and absence of the old
   static-path section.
2. Update mixed sibling tests to assert static entries include the inline location sentence while numbered sibling
   instructions still appear.
3. Add or adjust a chezmoi/global-config regression that matches the real `chezmoi` output shape with
   `~/.local/share/chezmoi/`.
4. Run the focused init-memory tests.
5. Run `sase init --check` and confirm the chezmoi memory file is current without editing it.
6. Because this changes repository files, run `just install` if needed and then `just check` before final response.
