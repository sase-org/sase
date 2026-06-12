---
create_time: 2026-06-12 12:11:48
status: done
prompt: sdd/prompts/202606/commit_tags.md
---
# Plan: Expand Conventional Commit Tag Guidance in `sase_git_commit` Skill

## Goal

Improve step 2 ("Determine the commit tag") of `src/sase/xprompts/skills/sase_git_commit.md` so agents pick from the
full set of conventional commit types, understand when each applies, and correctly mark breaking changes — because
projects may use automated release tooling (release-please / release-plz) that derives semantic version bumps and
changelog entries from these tags.

## Findings from Exploration

1. **The current `ref` tag is non-standard.** Conventional Commits, release-please, and release-plz all use `refactor`.
   This repo's own `.github/workflows/pr-title.yml` check allows only
   `feat|fix|perf|docs|ci|test|chore|refactor|build|deps` — a bare `ref` tag would fail it. Renaming `ref` → `refactor`
   is an objective correction, not just a style preference.
2. **This repo really does use release-please** (`release-please-config.json` + `.release-please-manifest.json`), so the
   "tags are more than cosmetic" note is literally true for the primary consumer of this skill.
3. **The file is a generated-skill source.** Per `memory/long/generated_skills.md`, after editing any file in
   `src/sase/xprompts/skills/`, we must run `sase init-skills --force` and then `chezmoi apply` so the rendered
   per-provider `SKILL.md` files pick up the change.
4. **No test churn expected.** `tests/test_commit_instructions.py` and `tests/main/test_init_skills_sources.py` assert
   on other parts of the skill body (wrapper invocation, `-f` flag guidance, `--resume`) — nothing pins the tag list.
   `sase_hg_commit.md` has no commit-tag section, so it is out of scope.

## Proposed Changes

All changes are in `src/sase/xprompts/skills/sase_git_commit.md`, step 2 of the Instructions section (inside the
existing `prettier-ignore` block).

### 1. Expand and reorder the tag list

Replace the current 4-tag list with the full conventional-commit type set, ordered so the agent checks the
release-relevant tags first and falls back to `chore` last. Each tag gets a crisp "use when" description:

- `feat` — adds or meaningfully improves a user-facing feature or capability (minor version bump). Feature _removal_ is
  also `feat`, but is backwards-incompatible and must carry the breaking-change marker (see below).
- `fix` — fixes a user-facing bug or incorrect behavior (patch version bump).
- `perf` — improves performance without changing external behavior.
- `refactor` — restructures code without changing external behavior; no new features, no bug fixes. (Renamed from the
  non-standard `ref`.)
- `docs` — documentation-only changes (README, docstrings, comments, docs site).
- `test` — adds or corrects tests only; no production code changes.
- `build` — build system, packaging, or dependency changes (e.g. `pyproject.toml`, lockfiles, justfile). Dependency
  bumps are conventionally scoped as `build(deps)` or `chore(deps)`.
- `ci` — CI/CD pipeline and workflow configuration changes.
- `style` — formatting/whitespace only; no change to code meaning.
- `revert` — reverts a previous commit; reference the reverted commit in the message body.
- `chore` — maintenance that fits none of the tags above (tooling config, housekeeping, asset updates).

Also briefly document the full header shape `tag(optional-scope)!: description` so the `!` placement below has context,
and note that the project may restrict the allowed set (e.g. via a PR-title check) — prefer a tag the project's history
already uses when in doubt.

### 2. Add a "tags drive releases" note

A short paragraph after the list: the project may use automated release tooling such as **release-please** or
**release-plz**, which parses these tags to compute the next semantic version and generate the changelog — `fix` →
patch, `feat` → minor, breaking change → major. Picking the wrong tag can ship a wrong version number or omit a
changelog entry, so the tag is not cosmetic.

### 3. Add explicit breaking-change instructions

Instruct the agent that any backwards-incompatible change (API, CLI, config format, behavior) MUST be marked using the
standard machinery both release-please and release-plz parse:

- Append `!` after the tag/scope: `feat!: drop legacy config format` or `feat(cli)!: ...`, **and/or**
- Add a footer line at the end of the commit message body:
  `BREAKING CHANGE: <description of what broke and how to migrate>` (the spec-standard token is singular
  `BREAKING CHANGE:`; `BREAKING-CHANGE:` is also accepted).

Recommend using the `!` suffix even when the footer is present, since squash-merge workflows keep the title but can
mangle bodies.

## Implementation Steps

1. Edit step 2 of `src/sase/xprompts/skills/sase_git_commit.md` as described above.
2. Run `sase init-skills --force`, then `chezmoi apply` (required by the generated-skills pipeline).
3. Run `just install` (ephemeral workspace) followed by `just check` to verify lint/tests/snapshots pass.

## Out of Scope

- `sase_hg_commit.md` (no commit-tag section exists there).
- Changing `pr-title.yml`'s allowed-type list or release-please config.
- Test changes (no tests assert on the tag list; `just check` will confirm).
