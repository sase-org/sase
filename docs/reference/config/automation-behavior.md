---
title: "Automation configuration behavior"
description: "Configuration for SDD, beads, and external issue mirroring."
---

# Automation configuration behavior

Configuration for SDD, beads, and external issue mirroring.

## sdd

Configuration for spec-driven development features, including prompt, tale, epic,
research, and bead storage.

```yaml
sdd:
  bead_refresh:
    mode: background
    ttl_seconds: 120
  repo:
    name: "" # provider-specific sidecar repo override
  push_after_commit: async
```

[Generated reference for `sdd`](automation.md#sdd)

The workspace provider owns storage selection. Built-in bare-git projects store SDD
under `sdd/`. Managed GitHub projects use a `--plans` sidecar cloned at
`sase/repos/plans`; every configured document role resolves at `sase/repos/<role>`. The
default-seeded `research` role derives `<owner>/<project>--research`. Current managed
initialization also records a `--beads` sidecar at `sase/repos/beads`. Unmigrated GitHub
projects retain their provider-backed `.sase/sdd/` clone. Materialized layouts record
metadata in the primary workspace's `.sase/sdd-store.json`. Providerless projects fall
back to a primary-workspace `.sase/sdd/` store. The retired `sdd.storage` and
`sdd.version_controlled` keys are ignored, stripped before validation, and reported by
`sase doctor` for cleanup. See [SDD Storage](../../contribute/sdd-storage.md) and
[Beads](../../beads.md).

The default current layout has a schema-version 3 `sidecar_repos` record: every recorded
role resolves to its role-specific clone, and bead state lives at the root of `--beads`.
A record without a beads role remains schema version 2 and resolves bead state to
`beads/` in `--plans`. Ordinary resolution preserves that compatibility shape. Running
managed `sase repo init` with the beads role enabled is the adoption step: it prepares
the dedicated sidecar and writes a schema-version 3 record. A project that disables or
otherwise omits the beads role stays on schema version 2. Initialization prepares
configured sidecars in its current workspace and re-records stale compatibility metadata
with the derived repository. Later workspaces clone lazy document roles on demand. The
legacy single-sidecar shape continues to resolve byte-for-byte as before.

Built-in bare-git projects also auto-create or refresh generated SDD guide files during
first-use `#git:<project>` initialization (target existing projects with their
`+<project>` [project tag](../macros/reference-syntax.md#project-tags)), existing
bare-repo registration, `#git`/workspace materialization, and the first in-tree SDD
write. Setup/materialization flows commit and push only those generated init paths with
an `Initialize SDD` init commit when needed.

For a repository whose own `sase/sase.yml` sets `is_sase_managed: true`, running
`sase repo init` or its `sase init repo` alias writes managed entries for plans, beads,
research, and agents, initializes configured sidecars, then refreshes generated guides
and the directory map. On GitHub it derives the remotes as `<owner>/<repo>--<role>` for
those four roles while honoring optional explicit `repo` pins. It initializes and pushes
every enabled entry, then maintains the split store record; the agents role is not part
of the SDD store record. Existing legacy `--sdd` files remain untouched locally and in
their remote, while normal SDD routing uses the configured sidecars. `--check` previews
provider and generated-file work without writing. Missing or false management markers
make both forms successful no-ops; invalid local marker configuration fails before
provider calls or writes.

Explicit initialization first performs authoritative provider discovery for every
enabled sidecar. Each missing GitHub repository triggers a separate prompt naming its
role and resolved repository; only `y` or `yes` authorizes that invocation to create it.
The prompts are default-no and unavailable on non-interactive stdin. Bare
`sase init --yes` cannot authorize repository creation: it reports a missing remote and
defers creation to an interactive `sase repo init` without failing automated onboarding.
`--check` remains network-free.

Source: `src/sase/default_config.yml`

## bead

Configuration for the bead issue tracker.

```yaml
bead:
  big_epic_phase_threshold: 5 # minimum authored phase count for llm_provider.big_epic_lander_model
  show:
    images: auto # image previews for sase bead show: auto, cells, kitty, or never
  task_triage:
    min_plus_ones: 1 # +1 reports a ready untyped/undeclared task needs before it earns a TaskTriage gate
    stale_after_days: 7 # age at which a still-sub-threshold ready task bead is stale
    stale_cleanup_min_beads: 10 # stale beads required before bead_stale_cleanup gates
  task_types: [] # optional catalog overrides and project-local types
  push_after_commit: true # compatibility field; current bead-work launches do not consult it
```

[Generated reference for `bead`](automation.md#bead)

Below the threshold, an epic land agent uses `llm_provider.epic_lander_model`. At or
above it, it uses `llm_provider.big_epic_lander_model` instead. An explicit land model
remains authoritative over both.

See
[`bead_task_triage`](../automation/scheduler-default-routines.md#checks-5-minute-interval)
for how the `task_triage` fields gate `TaskTriage` notifications,
[Task Triage Notification](../automation/notification-types.md#task-triage-notification)
for the post-upgrade dismissal of already-raised sub-threshold gates,
[Discovered Follow-Up Capture and Triage](../../beads.md#discovered-follow-up-capture-and-triage)
for the human-facing triage lifecycle.

In Launch Control (`,m`), the `big epic starts at` row shows this effective threshold
next to the two epic-lander rows. `e` or Enter opens a focused positive-integer editor,
and `r` previews an unset reset against `bead.big_epic_phase_threshold` in the writable
user-base config or its chezmoi source. There is no temporary override for this setting;
pressing `o` or `x` on the row only reports that Edit/Reset are available.

See [`docs/beads.md`](../../beads.md#sase-bead-work-target) for the current pre-spawn
checkpoint and publication flow.

Source: `src/sase/default_config.yml`

<a id="externalmirror"></a>

## external_mirror

Configuration for the external tracker mirror. See
[External Issue Mirroring](../../beads.md#external-issue-mirroring) and the
[`external_mirror` lane](../automation/scheduler-default-routines.md#external_mirror-15-minute-interval)'s
`external_issue_mirror` and `external_pr_mirror` jobs, the first production use of
`for_each: {source: projects}` fan-out.

One shared filter surface governs which tracker issues become beads
(`external_mirror.issues.filters`) and which remote pull requests become Patches
(`external_mirror.pull_requests.filters`). Each criterion is either a `*_globs` list
(accepting `!`-prefixed exclusions, matched like
[`file_hooks`](prompts-and-tools.md#filehooks)'s `path_globs`) or a `states` enum list.
A record matches a criterion if it matches any positive glob (or the criterion has no
positive globs) and matches no negative glob; a record is mirrored only when every
criterion accepts it, and matching is case-folded. Setting a criterion replaces the
shipped defaults for that criterion rather than appending to them. **Filters gate
creation only**: a record a filter now excludes keeps whatever bead or Patch it already
has, the mirror never deletes.

```yaml
external_mirror:
  issues:
    filters:
      author_globs: []
      label_globs: []
      title_globs: []
      states: []
  pull_requests:
    filters:
      author_globs: []
      base_ref_globs: []
      head_ref_globs:
        - "!release-please--*"
        - "!release-please/*"
        - "!release-plz-*"
        - "!release-plz/*"
      title_globs: []
      states: []
```

Pull requests ship with the four `head_ref_globs` exclusions above, so release-please
and release-plz PRs stop becoming Patches by default. Head ref is the key those defaults
filter on rather than author or title: release automation can author as a human account
on some repos, and PR titles are user-configurable, but the release branch name is
stable.

[Generated reference for `external_mirror`](repositories.md#external_mirror)

`external_mirror.exclude_labels` and `external_mirror.pr_authors` are deprecated aliases
for `external_mirror.issues.filters.label_globs` (folded in as negated globs) and
`external_mirror.pull_requests.filters.author_globs` (folded in as plain globs),
respectively. The fold applies only when the modern criterion is empty — a non-empty
modern criterion always wins, and the legacy key's value is then ignored.
`sase doctor -C config.external_mirror` flags both a set legacy key and the "set
alongside a non-empty modern criterion" case.

Records a filter drops are visible rather than silently missing:
`sase patch sync-external`'s table gets a `Filtered` column, `sase bead sync-external`'s
per-project line gains `filtered=<n>` when non-zero, and the Patches pane's project
banners show a `· M remote-only` suffix when a filtered-PR count is known.

Source: `src/sase/default_config.yml`

## Related

- [Automation and work tracking configuration](automation.md) — generated keys and
  defaults.
- [Beads](../../beads.md) — task tracking.
