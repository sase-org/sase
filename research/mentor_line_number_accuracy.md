# Mentor Line Number Accuracy

## Problem

Mentors select wrong line numbers when leaving comments. In the observed case, the mentor commented on
`prod_config.py:98` (the closing `"""` of a docstring) when the actual target was the `esc_queue` parameter at line 109.

## Root Cause Analysis

The mentor receives a **unified diff** (`git diff base...HEAD`) but must output **absolute file line numbers**. There is
no mechanism to reconcile these two coordinate systems. The LLM must mentally map from diff hunks to absolute positions,
which is error-prone because:

1. **Diff context is sparse** -- unified diffs only show ~3 lines of context per hunk. The LLM sees
   `@@ -70,20 +70,20 @@` headers and changed lines, but large unchanged regions are elided. It must infer absolute
   positions from those headers.

2. **The prompt gives no guidance** -- `mentor.yml` says "include the file path, line number" but never defines what
   coordinate system to use or how to derive line numbers.

3. **No full-file context** -- the mentor only gets the diff, not the full file content. It cannot cross-reference the
   diff against the actual file to verify its line number.

4. **No post-hoc validation** -- `sase comments` validates JSON schema but does NOT verify that the line number points
   to relevant code. A comment about `esc_queue` pointing at a docstring closing passes validation.

## Ideas to Fix / Mitigate

### Idea 1: Provide full file content alongside the diff

**How**: After the diff, include the full text of each modified file with line numbers. The mentor can then
cross-reference the diff against the numbered file to pick accurate line numbers.

**Tradeoff**: Increases prompt size significantly for CLs touching large files. Could be mitigated by only including
files that are small or have limited diff regions.

**Implementation**: Add a step to `mentor.yml` or the mentor workflow that reads each modified file and injects it as
numbered content after the diff.

### Idea 2: Add explicit line-number instructions to the prompt

**How**: Update `mentor.yml` to include instructions like:

> The line_number field must refer to the absolute line number in the modified file (the `+` side of the diff). Use the
> `@@` hunk headers to calculate absolute positions. The line number must point to the specific line you want changed,
> NOT a nearby landmark like a function signature or docstring.

**Tradeoff**: Cheap and easy to implement but still relies on LLM arithmetic, which is unreliable. Likely helps but
won't fully solve the problem.

### Idea 3: Post-hoc line number correction via content matching

**How**: After parsing the mentor's JSON, search the actual file content for a line that best matches the comment's
description. For example, if the description mentions `esc_queue`, find the line containing `esc_queue` nearest to the
stated line number and correct it.

**Tradeoff**: Requires heuristics for matching (keyword extraction from descriptions). Could mis-correct in ambiguous
cases. But it's a safety net that catches the most obvious mistakes.

**Implementation sketch**:

```python
def correct_line_number(comment: MentorComment, file_content: str) -> int:
    lines = file_content.splitlines()
    # Extract keywords from description (identifiers, string literals)
    keywords = extract_keywords(comment.description)
    # Search within a window around the stated line
    best_line = comment.line_number
    best_score = 0
    window = 30  # lines above/below to search
    for i in range(max(0, comment.line_number - window),
                   min(len(lines), comment.line_number + window)):
        score = sum(1 for kw in keywords if kw in lines[i])
        if score > best_score:
            best_score = score
            best_line = i + 1  # 1-indexed
    return best_line
```

### Idea 4: Use `sase comments` to show the code context back to the mentor

**How**: The mentor already runs `sase comments <file>` as a verification step. Enhance `sase comments` to show the code
snippet at the stated line number, so the mentor LLM can see whether its line number actually points to relevant code
and self-correct.

**Tradeoff**: Requires the mentor to actually look at the output and reason about correctness. This is already specified
in the prompt but may not be working effectively. Making the snippet more prominent (e.g., highlighting the exact target
line with an arrow) could help.

**Implementation**: Already partially implemented -- `sase comments` shows a code snippet centered on the line. Could
add a warning like "The highlighted line does not appear to match the comment description" via keyword matching.

### Idea 5: Use diff hunk ranges to constrain valid line numbers

**How**: Parse the unified diff to extract the set of actually-changed line ranges (the `+` side of `@@` headers). After
the mentor produces line numbers, validate that each line number falls within or near a changed region. Flag or
auto-correct comments pointing to unchanged code.

**Tradeoff**: Solid validation signal -- if a mentor comments on line 98 but the nearest changed hunk ends at line 85,
something is wrong. Doesn't work for comments about unchanged code that should have been changed (which is the case in
the observed bug -- the mentor correctly identified an unchanged line that needs updating).

**Limitation**: The current prompt says "Do NOT comment on code that was not modified / added by this CL" -- but the
observed bug is exactly a case where the mentor correctly flagged unchanged code that SHOULD change. So hunk-range
validation would reject this valid comment. This constraint may need rethinking.

### Idea 6: Two-pass approach -- find file, then find line

**How**: Split the mentor's task into two phases:

1. First pass: identify issues and the relevant file (no line number required)
2. Second pass: for each issue, provide the full file with line numbers and ask the mentor to pinpoint the exact line

**Tradeoff**: Doubles LLM invocations (cost and latency). But each pass is simpler and more likely to be accurate.

### Idea 7: Annotated diff with absolute line numbers

**How**: Pre-process the diff to annotate each line with its absolute file line number. Instead of raw unified diff, the
mentor sees:

```
  FILE: configs/monitoring/pod/drx_fe/prod_config.py
  70 |   from_addr='mdb.drx-fe-trafficking-denormalizer-f1@google.com',
  71 |   target_schema='monarch.BorgTask',
  72 |   workflow_type='escalator',
  73 | - esc_queue='gfp-api-trafficking-eng-oncall',
  73 | + esc_queue='gfp-api-trafficking-eng',
  74 | ):
```

**Tradeoff**: Requires writing a diff annotator but is straightforward. The LLM no longer needs to do hunk-header
arithmetic. This directly addresses the root cause.

**Implementation**: Write a function that parses unified diff output and annotates each line with its absolute
(new-file) line number. Use this annotated format in place of the raw diff in the mentor prompt.

## Recommended Approach

**Combine ideas 7 + 2 + 3** for a layered defense:

1. **Annotated diff** (Idea 7) -- eliminates the need for line-number arithmetic
2. **Better prompt instructions** (Idea 2) -- clarifies expectations
3. **Post-hoc correction** (Idea 3) -- safety net for remaining errors

Idea 7 is the highest-impact change because it removes the root cause (the LLM having to calculate absolute line numbers
from hunk headers). Ideas 2 and 3 provide additional assurance.

Idea 1 (full file content) is a good supplement if token budget allows, especially for small files. Idea 4 is already
partially in place and can be improved incrementally.
