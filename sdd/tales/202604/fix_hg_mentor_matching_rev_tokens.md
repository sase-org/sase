---
create_time: 2026-04-03 20:31:45
status: done
---

# Plan: Fix Missing MENTORS on hg/retired Mercurial plugin Due to Diff Header Parsing

## Problem Summary

`axe` is not adding a `MENTORS` field for some Mercurial-backed ChangeSpecs (observed on a machine using `retired Mercurial plugin`).

The logpack confirms hook completion for `pat_fix_pg_view_details` but no subsequent mentor profile registration in the
same period. This points to mentor profile matching returning no matches rather than hook lifecycle failure.

## Root Cause Hypothesis

Mentor profile matching depends on extracting changed file paths from commit diff text. The Mercurial parser currently
matches only very specific `diff -r` header formats with lowercase hex revisions.

That strict pattern can fail on valid Mercurial revision token variants (e.g., formats containing non-hex components
such as rev/hash forms, plus signs, uppercase, or other non-whitespace revision identifiers), which are
environment/config dependent. When parsing fails, changed-files becomes empty, no profile matches, and `MENTORS` is
never created.

## Implementation Plan

1. Harden Mercurial diff header parsing in `mentor_profile_matching` to accept generic non-whitespace Mercurial revision
   tokens while preserving support for both single-`-r` and double-`-r` forms.
2. Add focused regression tests covering at least one non-hex Mercurial header variant to prove matching no longer
   depends on lowercase-hex-only tokens.
3. Keep existing behavior unchanged for git diff headers and previously supported hg headers.
4. Run repository checks (`just install` if needed, then `just check`) to verify lint/type/tests all pass.

## Validation Strategy

- Unit tests should demonstrate extraction success for:
  - existing hg single-`-r` format,
  - existing hg double-`-r` format,
  - new non-hex revision token variant.
- Full `just check` should pass to guard against regressions.

## Risks / Mitigations

- Risk: Relaxing regex too much could match malformed lines.
  - Mitigation: Keep anchoring to `^diff -r` and explicit `-r` structure; only relax revision token character class.
- Risk: Hidden behavior differences across VCS backends.
  - Mitigation: No changes to git parsing path; only hg token matching is broadened.
