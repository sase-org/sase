---
create_time: 2026-06-27 08:41:33
status: done
prompt: sdd/prompts/202606/sorted_snippet_insertion.md
---
# Preserve Sorted Snippet Insertions

## Goal

When saving a prompt draft as an ACE snippet into an existing `ace.snippets` mapping, keep the snippet entries
alphabetically sorted by snippet trigger name when the existing entries are already sorted by name. If the existing
`snippets` mapping is not sorted by name, keep the current conservative behavior: append the new snippet without
reordering existing entries.

## Current Findings

The save-as-snippet flow writes through `src/sase/xprompt/snippet_config_yaml.py`. That writer already has a
sorted-insertion path, but it was copied from the xprompt config writer and uses a YAML entry-key sort key shaped like
`f"{name}:"`.

That key is appropriate for xprompts, where names can contain path-like separators and the existing tests intentionally
use the colon tie-break. It is not quite right for ACE snippet triggers. Snippet triggers are validated as
`[A-Za-z0-9_]+`, so users naturally expect the mapping to be sorted by the trigger name itself. With the current `name:`
sort key, a section containing `foo` followed by `foo1` can be interpreted as unsorted because `"foo1:"` sorts before
`"foo:"`, even though the names are alphabetically sorted as `foo`, `foo1`. In that case, a new snippet such as `foo0`
would be appended instead of inserted between `foo` and `foo1`.

## Plan

1. Add focused regression tests in `tests/xprompt/test_snippet_config_yaml.py`.
   - Cover a sorted existing `ace.snippets` mapping with prefix-related names such as `foo`, `foo1`, then insert `foo0`
     and assert the output is `foo`, `foo0`, `foo1`.
   - Cover insertion before the first entry and after the last entry in a sorted mapping, ideally with the same
     one-blank-line spacing pattern already used by the xprompt writer tests.
   - Cover the inverse case: a mapping that is sorted according to the old `name:` key but not sorted by snippet name
     should be treated as unsorted and should receive the new entry at the end without reordering.
   - Keep the existing comment-preservation and overwrite tests intact.

2. Change only the snippet YAML writer’s sort semantics.
   - In `src/sase/xprompt/snippet_config_yaml.py`, replace the xprompt-oriented entry-key sort helper with a
     snippet-name sort helper that compares `block.name` directly.
   - Use that helper both to decide whether the existing section is sorted and to locate the insertion point for the new
     name.
   - Keep the line-based minimal-edit approach: do not parse and re-dump the whole YAML file, and do not reorder
     existing snippets.
   - Leave `src/sase/xprompt/config_yaml.py` unchanged, because its current colon tie-break behavior is covered by
     xprompt-specific tests and has different naming semantics.

3. Preserve existing formatting behavior.
   - Continue using `_canonical_gap()` so a sorted mapping with blank lines between entries keeps that spacing around
     the inserted snippet.
   - Continue preserving comments and scaffolding around `ace:` and `snippets:`.
   - Continue replacing same-name snippets in place instead of moving them.

4. Verify with targeted and repo-level checks.
   - Run `pytest tests/xprompt/test_snippet_config_yaml.py`.
   - Run the create-snippet prompt-bar tests if the writer change impacts expected app-flow output:
     `pytest tests/ace/tui/actions/test_prompt_save_xprompt.py -k create_snippet`.
   - Because implementation changes will touch repo files, run `just install` if needed, then `just check` before
     finishing. If the known memory/provider-shim validation drift still blocks `just check`, report that explicitly and
     run the underlying lint/type/test gates directly as a fallback.

## Non-Goals

- Do not add a new UI confirmation or modal step.
- Do not sort an already-unsorted `snippets` mapping.
- Do not change xprompt config insertion ordering.
- Do not modify memory files or provider shims.
