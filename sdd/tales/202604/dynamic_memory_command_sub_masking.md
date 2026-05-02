---
create_time: 2026-04-25 10:23:33
status: done
prompt: sdd/prompts/202604/dynamic_memory_command_sub_masking.md
---
# Dynamic memory matches keywords inside `$(...)` command-substitution payloads

## Problem

A user reported that the dynamic-memory section in their agent's expanded prompt listed three matches whose keywords
clearly were NOT in the user-authored prompt:

```
### DYNAMIC MEMORY
- @.sase/memory/long-aaa-test-structure.md (memory/long/aaa_test_structure, matched: `test`)
- @.sase/memory/long-build-cleaner.md     (memory/long/build_cleaner,     matched: `build`, `BUILD`)
- @.sase/memory/long-growbird.md          (memory/long/growbird,          matched: `growbird`)
```

The user-authored xprompt was just:

```
#hg:yserve_read_grow Can you describe what this CL does? #cldd
```

None of `test`, `build`, `BUILD`, or `growbird` appears in that text — yet the matcher claims to have hit them.

## Root cause

`generate_dynamic_memory()` (`src/sase/memory/dynamic.py`) runs keyword matching against the prompt **after**
`process_xprompt_references()` has already expanded all `#xprompt` references AND **already resolved `$(...)` command
substitutions inside xprompt argument positions** via `_resolve_command_substitution_in_args()` in
`src/sase/xprompt/processor.py:370-373`.

Concretely the `#cldd` xprompt expands to two `#x(name, cmd)` references:

```
#x(cl_changes.diff, hg pdiff $(branch_changes | grep -v -E 'png$|fingerprint$') | perl -nE 'print s{google3/}{}gr')
#x(cl_desc, cl_desc --short)
```

When the xprompt processor parses each `#x(...)` reference it eagerly runs `process_command_substitution` on the _cmd_
argument, which executes `branch_changes | grep -v ...` and inlines its stdout — the list of files modified by the CL —
into the cmd string. The CL touches the `growbird` project, BUILD files, and test files, so the resolved cmd string
contains literal substrings `growbird`, `BUILD`, and `test`.

Then the `x` xprompt's body (`@$(sase_xcmd {{ name }} {{ cmd }})` from `default_config.yml:330-332`) renders with that
cmd, producing a literal text fragment like:

```
@$(sase_xcmd cl_changes.diff hg pdiff path/to/google3/.../growbird/foo.py path/to/google3/.../BUILD path/to/google3/.../foo_test.py | perl -nE ...)
```

That text fragment lives inside the prompt at the moment dynamic-memory matching runs. The whole-word, case-insensitive
regex search in `_keyword_matches` then happily finds `growbird`, `BUILD`, and `test` inside it — even though the user
authored none of those words.

The outer `$(sase_xcmd ...)` wrapper is itself unresolved at this point; it gets executed later by
`preprocess_prompt_late` to produce the final `@.sase/xcmds/cl_changes-260425_100108.diff` path that the agent
ultimately sees. So the keyword "evidence" the matcher used is _transiently_-present text that the user never wrote and
that doesn't even appear in the prompt the agent receives.

This same class of bug applies to _any_ xprompt whose arguments contain `$(...)` substitution: their resolved stdout
becomes part of the post- expansion prompt text and pollutes keyword matching with environment-derived data.

## Goals

1. Stop matching dynamic-memory keywords against text that came from `$(...)` command-substitution output (whether the
   substitution ran in xprompt args or remains as an outer `$(...)` placeholder).
2. Preserve current matching behavior against user-authored text and xprompt-defined static content (so existing
   memories that match e.g. `#feedback`-expanded keywords still trigger correctly).
3. Keep the change tightly scoped to dynamic-memory matching — don't change what text reaches the agent, only what the
   matcher sees.

## Non-goals

- Changing how `process_xprompt_references` resolves substitutions in arguments (used by many other call sites and
  removing it would break features like `#x(name, cl_desc --short)`).
- Changing the matching algorithm itself (positive/negative keywords, word-boundary regex, masking semantics) — only the
  input it sees.
- Reordering early/late preprocessing phases.

## Design

Mask `$(...)` payloads out of the prompt before keyword matching, mirroring the existing `_mask_negative_spans`
approach: blank the masked spans to spaces so offsets and surrounding word-boundaries are preserved.

Add `_mask_command_substitutions(prompt: str) -> str` in `src/sase/memory/dynamic.py`. It walks the prompt with the same
balanced- paren scan used by `sase.gemini_wrapper.file_references._find_command_substitutions` (the authoritative parser
already in the codebase) and replaces the entire span from `$` through the matching `)` with spaces. Honor the same
`\$(` escape behavior so escaped patterns are not masked.

Wire it into `generate_dynamic_memory` once, immediately after the existing `_strip_dynamic_memory_section` call:

```python
prompt = _strip_dynamic_memory_section(prompt)
prompt = _mask_command_substitutions(prompt)   # new
```

This guarantees:

- Outer unresolved `$(sase_xcmd ...)` payloads (where the inner inlined file-list lives) are masked out →
  `growbird`/`BUILD`/`test` from the reported scenario no longer match.
- Any future xprompt that bakes `$(...)` output into post-expansion text is automatically protected.
- User-authored prose outside any `$(...)` is untouched, so legitimate matches still fire.

### Reuse considerations

Rather than reimplement balanced-paren scanning, import `_find_command_substitutions` from
`sase.gemini_wrapper.file_references` (already used by `process_command_substitution`). It returns
`(start, end, command)` tuples, exactly what we need. Lifting it from private to module-level export is a tiny,
mechanical change.

If reusing it causes an undesired import direction (memory → gemini_wrapper), the alternative is a small local copy in
`dynamic.py` — the function is ~40 lines and stable. Decide during implementation; default is reuse.

## Test plan

Add cases to `tests/test_dynamic_memory.py` (or wherever `generate_dynamic_memory` / `_keyword_matches` is tested
today):

1. **`$(...)` content is ignored** — given a memory with keyword `growbird` and a prompt
   `Can you describe what this CL does? @$(echo path/to/growbird/foo.py)`, no match is produced.
2. **Nested `$(...)` is fully masked** — prompt `@$(outer $(inner build))` with memory keyword `build` produces no
   match.
3. **Escaped `\$(` is treated as literal text** — prompt `discuss \$(build) options` with keyword `build` DOES match
   (escape semantics preserved).
4. **Keywords outside `$(...)` still match** — prompt `Please run the build $(echo skip)` with keyword `build` matches.
5. **Negative-keyword masking still composes correctly** when a positive hit lies inside `$(...)` and a negative hit
   lies outside (or vice versa) — i.e. `_mask_command_substitutions` runs before `_mask_negative_spans` and offsets stay
   aligned.
6. **End-to-end regression** — replicate the user's reported xprompt shape (`#cldd`-style expansion producing
   `@$(sase_xcmd cl_changes.diff ... google3/.../growbird/... | perl ...)`) and assert no matches against
   `growbird`/`BUILD`/`test` keywords.

## Risk and rollout

- **Behavior change**: any existing memory that was _intentionally_ matching against text inside `$(...)` will stop
  firing. This seems unlikely to be deliberate (and is the bug being reported), but worth noting in the commit message.
- **Surface area**: one function, one call site, plus tests. No changes to prompt content delivered to agents. Safe to
  ship without a flag.
- **Verification**: `just check` and the new tests; spot-check by re-running the reported scenario after the fix and
  confirming the DYNAMIC MEMORY section no longer lists the three spurious entries.

## Files touched

- `src/sase/memory/dynamic.py` — add `_mask_command_substitutions`, call it in `generate_dynamic_memory`.
- `src/sase/gemini_wrapper/file_references.py` — _(optional)_ export `_find_command_substitutions` (rename to
  `find_command_substitutions`) so `dynamic.py` can reuse the parser. Keep a private alias if any downstream code
  referenced the underscored name.
- `tests/test_dynamic_memory*.py` — new test cases per the test plan.
