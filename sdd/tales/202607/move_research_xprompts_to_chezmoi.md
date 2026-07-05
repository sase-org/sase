---
create_time: 2026-07-05 07:05:36
status: wip
prompt: sdd/prompts/202607/move_research_xprompts_to_chezmoi.md
---
# Move Research XPrompts from sase Defaults to Chezmoi + Add `@research` / `@research_assist` Model Aliases

## Goal

Relocate the entire research xprompt family from sase's shipped defaults into Bryan's chezmoi repo (his global,
user-level SASE configuration source), and introduce two custom model aliases that the relocated `#research_swarm`
xprompt will use:

- `@research` → `codex/gpt-5.5` — used by the 1st research agent (`research.@.cdx`) and the 3rd agent (the consolidator,
  `research.@.final`).
- `@research_assist` → `claude/opus` — used by the 2nd research agent (`research.@.cld`).
- The 4th agent (`research.@.image`) keeps its hardcoded `%model:codex/gpt-5.5`.

## Current State (verified)

The research family is shipped in two default locations in the sase repo:

1. **`src/sase/default_xprompts/research_swarm.md`** — 4-segment multi-agent xprompt:
   - Segment 1: `%name:research.@.cdx %model:codex/gpt-5.5 %g:research {{ prompt }} #research`
   - Segment 2: `%name:research.@.cld %m:claude/opus %g:research {{ prompt }} #research`
   - Segment 3: `%name:research.@.final %wait:research.@.cdx %wait:research.@.cld %g:research` (consolidator; currently
     has **no** model directive)
   - Segment 4:
     `%name:research.@.image %model:codex/gpt-5.5 %wait:research.@.final %g:research #fork:research.@.final #research/image`
2. **`src/sase/default_xprompts/old_research_swarm.md`** — legacy 3-segment swarm (references `#research`,
   `#research/more`, `#research/image`).
3. **`src/sase/default_config.yml`** `xprompts:` block (lines ~554–571) — four config-based entries: `research/image`,
   `research/more`, `research/prompt`, and `research`.

Chezmoi already manages both destinations:

- `~/.local/share/chezmoi/home/dot_xprompts/` → `~/.xprompts/` (file-based user xprompts; loader priority 3 — higher
  than built-ins). Note: file-based xprompt dirs are globbed **flat** (`*.md` only), so slash-named xprompts like
  `research/image` cannot live here; they must be config-based.
- `~/.local/share/chezmoi/home/dot_config/sase/sase.yml` → `~/.config/sase/sase.yml` (already has an
  `llm_provider.model_aliases` section with a commented-out `custom:` example, and an `xprompts:` keep-sorted block).
  Verified currently in sync with the applied file.

Custom model aliases are fully supported today: `llm_provider.model_aliases.custom.<name>` objects with required `model`
and `description` keys, referenced from prompts as `%model:@<name>` / `%m:@<name>`
(`src/sase/llm_provider/config.py::resolve_model_alias`, schema in `src/sase/config/sase.schema.json`). The names
`research` and `research_assist` do not collide with any builtin role alias (`default`, `coder`, `claude_coder`,
`codex_coder`, `epic_creator`, `epic_lander`, `phase_worker`).

The chezmoi repo is a linked repo configured with `workspace.strategy: none`, so it is edited directly at
`~/.local/share/chezmoi/`.

## Changes

### Part 1 — Chezmoi repo (`~/.local/share/chezmoi/`)

Do this part first so the research xprompts never disappear from Bryan's environment while the sase-side removal is in
review.

#### 1a. Add custom model aliases to `home/dot_config/sase/sase.yml`

Replace the commented-out `custom:` example under `llm_provider.model_aliases` with:

```yaml
custom:
  research:
    model: codex/gpt-5.5
    description: "Primary research-swarm agents: the lead researcher and the consolidator."
  research_assist:
    model: claude/opus
    description: "Assisting (second-opinion) research-swarm agents."
```

(Indented to sit alongside the existing `builtin:` map. Both `model` and `description` are required by the config schema
for custom aliases.)

#### 1b. Move the four config-based research xprompts into `home/dot_config/sase/sase.yml`

Copy the `research/image`, `research/more`, `research/prompt`, and `research` entries **verbatim** from
`src/sase/default_config.yml` into the existing `xprompts:` keep-sorted block (they sort between `rchat` and the
end-of-block marker; keep-sorted line order is `research/image`, `research/more`, `research/prompt`, `research` —
matching their current order in `default_config.yml`).

#### 1c. Move `research_swarm.md` to `home/dot_xprompts/research_swarm.md`

Copy `src/sase/default_xprompts/research_swarm.md` (frontmatter unchanged) with these model-directive edits:

- Segment 1: `%model:codex/gpt-5.5` → `%model:@research`
- Segment 2: `%m:claude/opus` → `%m:@research_assist`
- Segment 3: add `%m:@research` after the name, i.e.
  `%name:research.@.final %m:@research %wait:research.@.cdx %wait:research.@.cld %g:research`
- Segment 4: **unchanged** (`%model:codex/gpt-5.5` stays hardcoded)

Everything else (description, `input:` frontmatter, `{% raw %}{{ wait_chats }}{% endraw %}` body, consolidation
instructions) is copied as-is. The `.cdx`/`.cld` agent-name suffixes stay: they still match what the aliases resolve to
today.

#### 1d. Move `old_research_swarm.md` to `home/dot_xprompts/old_research_swarm.md`

Verbatim copy of `src/sase/default_xprompts/old_research_swarm.md` (its `#research`, `#research/more`, `#research/image`
references keep resolving via the entries added in 1b).

#### 1e. Apply and verify

- Run the chezmoi repo's lint/check target if one exists (`just --list` in `~/.local/share/chezmoi/`; it has a
  keep-sorted-based lint) to keep the keep-sorted blocks valid.
- Run `chezmoi apply` so `~/.xprompts/research_swarm.md`, `~/.xprompts/old_research_swarm.md`, and
  `~/.config/sase/sase.yml` are updated.
- Verify: `sase xprompt list | grep research` shows all six names, and `sase xprompt show research_swarm` (or
  equivalent) shows the user-level source with the `@research` / `@research_assist` directives. `sase doctor` should
  pass schema validation for the new custom aliases.

### Part 2 — sase repo

#### 2a. Delete the default xprompt files

- Delete `src/sase/default_xprompts/research_swarm.md` and `src/sase/default_xprompts/old_research_swarm.md`.
- Add `src/sase/default_xprompts/.gitkeep` (repo already uses `.gitkeep` elsewhere) so the directory survives in fresh
  clones/wheels. This keeps `get_sase_package_default_xprompts_dir()` from logging its missing-directory warning and
  keeps the "Built-in default_xprompts/" entry in the xprompt location modal pointing at a real directory. A non-`.md`
  file is never loaded as an xprompt, and `load_xprompts_from_default_files()` simply returns `{}` for the now-empty
  dir. The loading mechanism itself stays (it is generic and also exercised by sase-core's LSP via
  `SASE_XPROMPT_DEFAULT_DIR`).

#### 2b. Remove the config-based research entries from `src/sase/default_config.yml`

Delete the `research/image`, `research/more`, `research/prompt`, and `research` entries from the `xprompts:` keep-sorted
block (lines ~554–571). No other entry in `default_config.yml` references them (verified — the only `#research`
reference is inside `research/prompt` itself).

#### 2c. Update tests (`tests/test_xprompt_loader_config.py`)

Only three tests depend on the real shipped research defaults:

1. `testload_xprompts_from_default_files_includes_research_swarm` — rewrite as a fixture-based test of the default-files
   mechanism: create a tmp `default_xprompts/` dir with a small fixture `.md` (frontmatter + body), patch
   `sase.xprompt.loader_sources.get_sase_package_default_xprompts_dir` to return it, and keep the meaningful assertions
   (name derived from filename, `source_path`, content loaded). Drop the research-specific content assertions (the
   "shipped defaults must inline %model directives" constraint no longer applies to anything shipped).
2. `test_default_file_xprompt_not_project_namespaced` — same tmp-dir patch with a fixture default xprompt; keep the
   "default file xprompts stay global / are not project-namespaced" assertions against the fixture name.
3. `test_research_xprompts_load_from_default_config` — repoint at still-shipped `default_config.yml` xprompts to
   preserve coverage of config-based loading and input parsing: e.g. assert `review` and `prompt/review` load with
   `source_path == "default_config"`, and that `prompt/review`'s single `prompt` input is `InputType.TEXT` (it has the
   same `input: {prompt: text}` shape the research test relied on). Rename the test accordingly.

No other test changes are needed (verified): `test_multi_agent_xprompt_expansion.py`,
`test_xprompt_catalog_classification.py`, `test_xprompt_references.py`, `tests/doctor/test_checks_config.py`, the ACE
TUI tests, and the visual snapshot suite all use "research"-named **inline/tmp fixtures** or opaque prompt strings and
never load the shipped defaults.

#### 2d. Update `docs/xprompt.md`

Remove the six research rows (`#research`, `#research/image`, `#research/more`, `#research/prompt`, `#research_swarm`,
`#old_research_swarm`) from the "Built-in XPrompts" table (lines ~831–836). Leave the `%name:research.@.final` mentions
later in the doc alone — those are generic naming/templating syntax examples, not claims about shipped defaults.

#### 2e. No sase-core changes

`../sase-core` only references `default_xprompts` as a generic directory mechanism, and its LSP tests construct their
own tmp `default_xprompts/research_swarm.md` fixture paths — nothing depends on the actual shipped files (verified).

## Verification

1. Chezmoi side (after `chezmoi apply`): `sase xprompt list` shows all six research xprompts sourced from user config;
   launching-path sanity via `sase doctor` (validates the new `model_aliases.custom` entries against the schema).
2. sase repo: `just install`, then `just check` (must pass — includes the rewritten loader tests).

## Notes / Decisions

- **Ordering**: land the chezmoi changes (Part 1) before the sase PR (Part 2) so `#research_swarm` and friends remain
  available continuously. Once both land, the user-level definitions simply stop shadowing anything.
- Slash-named xprompts (`research/*`) go into `sase.yml` config because file-based xprompt directories only glob flat
  `*.md` files; the two swarm xprompts go into `~/.xprompts/` as files because they are multi-segment markdown prompts
  with frontmatter, matching the existing `pick_plan.md` pattern there.
- `old_research_swarm` is moved verbatim (not modernized, not dropped) — it stays functional because its `#research*`
  references move with it.
- Agent names `research.@.cdx` / `research.@.cld` are kept even though models are now alias-driven; today the aliases
  resolve to codex/claude respectively, so the names remain accurate. Renaming is out of scope.
