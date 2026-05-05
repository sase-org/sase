---
create_time: 2026-05-04 20:03:57
status: done
prompt: sdd/prompts/202605/inline_directive_vcs_xprompt_inheritance.md
---
# Fix inline-directive VCS inheritance for multi-agent xprompts

## Context

The Telegram launch shown in the screenshot used a prompt shaped like:

```text
%n:abq #gh:sase #research_swarm:: Can you help me review ...
```

`#research_swarm` is a built-in multi-agent xprompt whose body expands to:

```text
{{ prompt }} #research

---

%w #resume #research/more %m:opus

---

%w #resume #research/image
```

The first generated agent was launched in the `sase` workspace, but the follow-up agents shown by Telegram were launched
as home-mode prompts:

```text
%w:abq #cd:~ #resume:abq #research/more %m:opus
%w:abq.r1 #cd:~ #resume:abq.r1 #research/image
```

That proves the prior workflow-executor fix did not cover this path. This path is multi-agent xprompt expansion at
launch time, before the workflow executor is involved.

## Root Cause

`src/sase/agent/multi_agent_xprompt.py` already has VCS inheritance for expanded multi-agent xprompts:

- top-level references like `#gh:sase #research_swarm:: ...` correctly propagate `#gh:sase` into every generated
  segment;
- embedded references use `_leading_vcs_ref_text(segment)` to find a VCS ref in the original segment and apply it to
  generated follow-up segments;
- default home-mode normalization later adds `#cd:~` only to generated segments that still lack any workspace ref.

The missed case is Telegram-style inline directives. `_split_leading_directives()` only treats full directive lines as
leading directives:

```text
%n:abq
#gh:sase #research_swarm:: ...
```

It does not handle same-line directive prefixes:

```text
%n:abq #gh:sase #research_swarm:: ...
```

So `_leading_vcs_ref_text("%n:abq #gh:sase #research_swarm:: ...")` returns `None`. The first expanded segment keeps the
original prefix because it is reconstructed around the matched xprompt reference, but follow-up segments receive no
inherited VCS tag. The launcher then sees bare follow-ups and correctly applies the default `#cd:~`, which masks the
original `#gh:sase` intent.

This explains why the previous commit's tests passed: they exercised workflow prompt-step inheritance and direct
multi-agent inheritance without a same-line `%n` directive before the VCS tag.

## Desired Behavior

All launch directive layouts should inherit the same VCS ref:

```text
#gh:sase #research_swarm:: task
%n:abq #gh:sase #research_swarm:: task
%n:abq %model:opus #gh:sase #research_swarm:: task
%n:abq #gh_sase #research_swarm:: task
```

Each should expand into generated segments where every segment has the inherited VCS selector, and no follow-up segment
falls back to `#cd:~`.

Explicit workspace refs in generated segments must still win. If a generated follow-up already contains `#cd:~`,
`#git:...`, `#gh:other`, or another workspace ref, the inherited tag should not override it.

## Implementation Plan

1. Reuse the parser's same-line directive logic instead of maintaining a narrower directive splitter in the multi-agent
   xprompt module.
   - The parser-side `_DIRECTIVE_PREFIX_RE` already recognizes consecutive `%...` tokens at the start of a prompt.
   - Add or adapt a small helper in `multi_agent_xprompt.py` that splits leading whitespace, same-line directive tokens,
     directive-only lines, and the remaining body in a way that preserves existing output formatting.
   - Keep the helper local unless there is a clean public parser utility already available.

2. Make VCS discovery see past inline directives.
   - Update `_leading_vcs_ref_text()` and `extract_top_level_xprompt_reference()` so `%n:abq #gh:sase #research_swarm::`
     is treated like `#gh:sase #research_swarm::` for VCS/xprompt detection.
   - Ensure fallback known-project refs such as `#gh_sase` and `#gh:sase` both work even when the `gh` provider plugin
     is not registered.

3. Preserve directive placement when prefixing generated follow-up segments.
   - Generated segments such as `%w #resume #research/more %m:opus` should become:

     ```text
     %w #gh:sase #resume #research/more %m:opus
     ```

   - This matches existing parser behavior and avoids moving `%w`, `%m`, `%n`, or `%wait` directives behind the VCS tag.

4. Add focused regressions.
   - Extend `tests/test_multi_agent_xprompt.py` for same-line `%n` plus `#gh:sase`.
   - Add coverage for multiple same-line directives before the VCS tag.
   - Add coverage for underscore known-project fallback (`#gh_sase`) because Telegram pending actions commonly contain
     that form.
   - Assert default normalization does not inject `#cd:~` after expansion in these cases.

5. Validate with focused tests first, then repo checks.
   - Run:

     ```bash
     .venv/bin/pytest tests/test_multi_agent_xprompt.py tests/test_xprompt_parsing.py
     ```

   - Because this repo's memory requires it after changes, run:

     ```bash
     just install
     just check
     ```

   - If `just check` fails outside touched files, report the exact unrelated failure and run the closest passing code
     checks.
