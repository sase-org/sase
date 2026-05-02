---
create_time: 2026-03-29 17:10:01
status: PROPOSED
prompt: sdd/prompts/202603/fix_strip_pr_tags_blank_lines.md
---

# Fix: `strip_pr_tags()` fails to strip tags separated by blank lines

## Problem

When creating a ChangeSpec from a CL description, `BUG=483686843` leaks into the DESCRIPTION field. The other trailing
PR tags (`AUTOSUBMIT_BEHAVIOR=`, `R=`, `MARKDOWN=`, etc.) are correctly stripped, but `BUG=` remains because it is
separated from the contiguous tag block by a blank line.

### Root Cause

`strip_pr_tags()` in `src/sase/vcs_provider/config.py` scans upward from the last non-blank line looking for a
**contiguous** block of `KEY=VALUE` tag lines. When it encounters a blank line, it **stops scanning** and only strips
the tags below that blank line.

This fails when the description has the form:

```
Body text

BUG=483686843

AUTOSUBMIT_BEHAVIOR=SYNC_SUBMIT
R=startblock
MARKDOWN=true
STARTBLOCK_AUTOSUBMIT=yes
WANT_LGTM=all
```

The function strips `AUTOSUBMIT_BEHAVIOR` through `WANT_LGTM` (contiguous block at the end), but `BUG=483686843`
survives because the blank line breaks the contiguity check.

### How this format arises

The commit workflow calls `_append_pr_tags()` which appends all tags as one block: `f"{message}\n\n{tag_lines}"`.
However, if the agent already included `BUG=483686843` in its commit message body (e.g., because the bug ID was part of
its prompt context), the result is:

```
<body text>
BUG=483686843          <-- agent-written, in the body
                       <-- blank line from _append_pr_tags separator
BUG=483686843          <-- appended by _append_pr_tags
AUTOSUBMIT_BEHAVIOR=...
...
```

`strip_pr_tags()` removes the bottom contiguous block (including the duplicate BUG=) but leaves the agent-written
`BUG=483686843` because the blank line breaks the scan.

## Fix

Modify `strip_pr_tags()` to **skip blank lines** when scanning upward through the trailing tag region. Currently, a
blank line triggers `else: break`. The fix changes this to `continue` scanning past blank lines, only breaking on actual
non-tag content.

### Before

```python
for idx in range(last_non_blank, -1, -1):
    if _TAG_PATTERN.match(lines[idx].strip()):
        tags_start_idx = idx
    else:
        break
```

### After

```python
for idx in range(last_non_blank, -1, -1):
    stripped = lines[idx].strip()
    if _TAG_PATTERN.match(stripped):
        tags_start_idx = idx
    elif stripped == "":
        continue
    else:
        break
```

### Safety analysis

The risk is that body content matching `^[A-Z][A-Z0-9_]*=` above a blank line could be accidentally stripped. This is
extremely unlikely in commit messages because:

1. The scan still requires the description to END with tag-like lines (the initial `last_non_blank` check)
2. Non-tag body text (e.g., `"Some explanation here"`) will still trigger `break`
3. The pattern `^[A-Z][A-Z0-9_]*=` is very specific (all-caps with underscores, followed by `=`)

The existing test `test_tag_like_line_in_middle_not_stripped` (`"Fix bug\n\nAUTO=yes\n\nMore text after"`) continues to
pass because the description ends with `"More text after"` which is not a tag, so the scan never reaches `AUTO=yes`.

## Test plan

1. Add test: tags separated by blank line are all stripped
2. Add test: multiple blank-line-separated tag groups are stripped
3. Verify existing tests still pass (especially `test_tag_like_line_in_middle_not_stripped`)
4. Run `just check`
