---
create_time: 2026-04-24 21:13:25
status: done
prompt: sdd/prompts/202604/init_skills_prettier_format.md
---
# Plan: Format `sase init-skills` Output With Prettier

## Problem

`sase init-skills` writes generated `SKILL.md` files into the chezmoi repo (under
`~/.local/share/chezmoi/home/dot_*/skills/.../SKILL.md` and provider-specific variants). The chezmoi
repo's CI runs:

```
prettier --check --prose-wrap=always --print-width=120 "**/*.md"
```

When the source templates in `src/sase/xprompts/skills/*.md` contain hard-wrapped prose (around column 118 to keep
template lines readable in editors) and Jinja2 substitutes shorter strings (e.g. `{{ provider_name }}` → `Claude` /
`Codex` / `Gemini`), the generated file ends up with prematurely-wrapped lines. Prettier with
`--prose-wrap=always --print-width=120` then re-joins them, so a fresh `prettier --check` fails.

Concrete evidence:

- Failed CI run `24915774540` — `[warn] home/dot_*/skills/sase_plan/SKILL.md` for all four providers (Claude, Codex,
  Gemini and external providers).
- Manual fix commit `dcc0ad47 chore: Format with prettier` showed the diff was purely line-rejoining (no semantic
  change).
- Source `src/sase/xprompts/skills/sase_plan.md` contains lines like
  `Use this skill … This replaces {{ provider_name }}'s native plan mode, which is` followed by `disabled.` on the next
  line — fits in 120 cols after substitution and so prettier joins them.

The same root cause will recur whenever any template's prose lines fall under the 120-column limit after rendering.

## Goal

Make `sase init-skills` produce output that already satisfies the chezmoi CI's prettier check, so committing the
generated files never creates a CI failure that has to be patched up by hand.

## Design

Pipe the rendered `SKILL.md` content through `format_with_prettier()` before writing it to disk. This helper already
exists at `src/sase/gemini_wrapper/file_references.py:451` and uses the exact same args the chezmoi CI uses
(`--prose-wrap=always --print-width=120 --parser=markdown`), so by construction the output will pass the check.

The helper already degrades gracefully when prettier is missing (returns input unchanged). For `init-skills`
specifically we want to be slightly louder about that case, because shipping un-prettified output is the whole bug —
emit a single `init-skills: prettier not found on PATH; output may not match chezmoi CI formatting` warning to stderr
(only once per invocation, not per file).

### Where to apply

In `src/sase/main/init_skills_handler.py`:

- `_render_skill` already strips `<!-- prettier-ignore -->` comments and collapses blank lines. Prettier formatting is
  the natural next step, but it must run on the **final assembled output** (frontmatter + body), not the body in
  isolation, because:
  - Prettier formats the YAML frontmatter as well (it normalizes whitespace inside `---` blocks).
  - Running it on the joined string is one fewer subprocess call per skill.
- So the call goes inside `handle_init_skills_command`, right after `output = _build_output(...)` and before the
  existing-file comparison / write. The comparison must happen against the post-prettier text so that
  `_prompt_overwrite`'s "unchanged, skipping" path also stays correct.

### Idempotence

`format_with_prettier` is idempotent on already-formatted text (that's a property of prettier itself). So re-running
`init-skills` on output it already wrote produces no further diffs — preserving the existing "Nothing to commit" code
path in `_deploy_to_chezmoi`.

### Frontmatter compatibility

`_build_output` constructs three frontmatter shapes:

1. Single-line `description: ...`
2. Folded multi-line block `description:\n  wrapped...` (using `textwrap.fill` at width 118)
3. Literal block `description: |\n  line1\n  line2\n`

Prettier's default markdown parser reformats YAML frontmatter (it's a documented prettier feature). We need to verify
all three shapes survive the round-trip. If shape (2) — manual `textwrap.fill` indentation — gets rewritten differently
by prettier, that's fine: prettier's version is the canonical one and we can simplify `_build_output` to just emit the
raw description and let prettier wrap it. (If verification shows shape 2 already matches prettier output, no change
needed.)

### Underscore handling

`format_with_prettier` already unescapes `_` → `_` in a loop to undo prettier's underscore-escaping of identifiers.
Skill files contain plenty of identifiers (`sase_plan`, `sase_git_commit`, `provider_name`), so this is exactly the
behavior we want — no extra work needed.

## Tasks

1. **Wire prettier into `handle_init_skills_command`** (`src/sase/main/init_skills_handler.py`):
   - Import `format_with_prettier` lazily (matching the pattern in `plan_command_handler.py:48` and `sdd/files.py:151`)
     to avoid pulling `gemini_wrapper` into the init-skills import path at module load.
   - Call it on `output` right after `_build_output`.
   - Emit the "prettier not found" warning at most once per invocation (track a flag on the local function scope).

2. **Verify frontmatter shapes** by running the new code locally against all three shapes and confirming idempotence:
   - Single-line: `sase_git_commit` (short description).
   - Long single-line that triggers `textwrap.fill`: pick or synthesize a description >120 chars.
   - Multi-line literal block: pick or synthesize a description with explicit `\n`.

   If shape (2) is rewritten by prettier, simplify `_build_output` to emit the raw single-line description in that case
   and rely on prettier to wrap it.

3. **Tests** (`tests/main/test_init_skills_handler.py`):
   - Add a test that renders a skill source whose body would be under-wrapped after Jinja substitution (mimicking the
     `sase_plan` regression) and asserts the written file passes
     `prettier --check --prose-wrap=always --print-width=120 --parser=markdown` (skip if prettier is missing on the test
     machine — `pytest.importorskip`-style skip via `shutil.which`).
   - Add a test that running `init-skills` twice in a row produces identical bytes the second time (idempotence guard).
   - Add a test that asserts the warning is emitted (and only once) when `shutil.which("prettier")` returns `None`, by
     patching it.

4. **Regenerate skills locally** by running `sase init-skills --force --no-commit --no-push --no-apply` and visually
   diffing the result against the current chezmoi `HEAD` to confirm the diffs are only the under-wrap fixes that the
   manual commit `dcc0ad47` had to apply.

5. **Run `just check`** in `sase_101` and in `~/.local/share/chezmoi/` (per `memory/long/external_repos.md`) before
   reporting done.

## Out of Scope

- Fixing the source templates' line widths. The point of this change is that the source templates can stay
  editor-friendly; the generator handles wrapping authoritatively.
- Touching the chezmoi CI workflow. The contract we want is "init-skills output passes chezmoi CI as-is," which means
  meeting CI's existing rules, not loosening them.
- Running prettier on non-skill files written by other sase commands. Those already use `format_with_prettier` where
  appropriate (`plan_command_handler`, `sdd/files`).

## Risk and Reversibility

- Low risk: prettier is already a runtime soft-dep used in several other sase commands; the helper has graceful
  fallback.
- Reversible: a single-call addition in one handler. Easy to revert if it interacts badly with any specific skill
  template.
- Failure mode if prettier is absent: same behavior as today (un-formatted output), but with a clear warning telling the
  user why their commit may fail CI.
