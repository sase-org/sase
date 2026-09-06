# Artifacts pane contract

`ArtifactsPaneContract` is the host-owned record that decides what a pane can do before
widgets, keybindings, or document providers run. Built-in panes compile the contract
from `_artifact_tab_contract_adapters.py`; schema-v1 document providers compile it from
their `ref` declaration.

Providers declare facts. The host derives capabilities from those facts through named
rules, then every Artifacts surface — footer, help, command palette, copy registry, and
the conformance suite — reads the contract instead of comparing pane ids.

Inspect a compiled pane with `sase artifact pane show <pane_id>` (`-j` for JSON). Every
closed capability is printed ON or OFF with the named rule, declared fact, and reason
behind the verdict. A provider may suppress an earned capability with a non-empty reason
string; it may never assert a capability it has not earned.

## Patch is contract-in, spec-out

`patch` is a reserved kind and can never be a document provider. Patch consumes the
contract from a built-in Python adapter table and never declares a `ref` spec. Do not
"fix" that asymmetry: a sidecar `ref.use: builtin@patch` is invalid by design. Patch
still earns capabilities the same way every other pane does; it just does not publish a
provider spec for them.

## Capability vocabulary

`PaneCapability` is a closed enum of verbs the host already implements. A capability
enables registered host behavior; it never carries callbacks, widgets, colors, or
provider code.

| Capability              | Earned when                                 | Host actions (when ON)                               |
| ----------------------- | ------------------------------------------- | ---------------------------------------------------- |
| `entry_navigation`      | Inventory or a built-in list adapter        | Pane `j`/`k` plus `jump_to_entry`                    |
| `entry_open`            | Inventory or a built-in list adapter        | Pane Enter / view-selected                           |
| `filter_session`        | Inventory plus fields                       | Persistent idle filter row; `/` / `f` / `edit_query` |
| `refresh`               | Always (host)                               | `refresh` (`R`)                                      |
| `project_scope`         | Adapter declares project scoping            | `pick_artifacts_project`                             |
| `stable_marks`          | Inventory or a built-in list adapter        | `toggle_mark` / `clear_marks`                        |
| `detail_scroll`         | A detail surface is declared                | Detail `Ctrl+D` / `Ctrl+U`                           |
| `stable_reference_copy` | Stable identity facts                       | `artifacts_copy_reference` (`y`)                     |
| `query_history`         | Inventory plus fields                       | `edit_query` plus previous/next query history        |
| `saved_queries`         | Inventory plus fields                       | `start_saved_query_mode`                             |
| `versions`              | Revision facts                              | Files previous/next version                          |
| `mutation`              | Built-in adapter with `can_mutate`          | Bead/Patch mutate actions                            |
| `plan_approve`          | Built-in Plan adapter                       | `plans_approve`                                      |
| `plan_reject`           | Built-in Plan adapter                       | `plans_reject`                                       |
| `relations`             | At least one validated relation declaration | `<` / `>` / `~`                                      |
| `grouping`              | At least one grouping mode                  | `h`/`l`/`H` plus grouping-cycle                      |
| `status_counters`       | At least one declared status counter        | Presentation-only (relation glyphs / count lanes)    |
| `shell`                 | Always (host)                               | Presentation-only shared chrome                      |

Derivation is a named pure rule per capability. Degraded panes keep only `refresh` and
`shell`. The conformance suite asserts that every ON capability's host actions are
registered, that every contract-declared key on a pane resolves to the action the
contract names (no double-booked `o`), and that every OFF capability has an auditable
verdict.

Host-owned list paging is not a pane capability. Every pane with `filter_session`
accepts a `limit:N` token that caps how many matched rows the list shows. ACE extracts
it before dialect parse, then slices. Startup writes `limit:<ace.page_size>` into each
pane's default query when no `limit:` is present; `limit:all` is the unlimited synonym
on every pane, and the shared parser also accepts `limit:0` for the same state. `Ctrl+J`
(`artifacts_load_more`) raises the cap by one page and `Ctrl+K` (`artifacts_unload`)
lowers it, never dropping below one page. See [ACE Artifacts](ace.md) for the
user-facing keys and coverage badges.

## Declarative `ref.pane`

`ref.pane` is Python-owned presentation data at document-provider schema version 1. The
Rust provider-spec wire stays at v1; this block never crosses that wire. A sidecar
declares description copy, row template, sort, facets, grouping, and empty state as data
and inherits the host query language, relations, marks, copy, help, and chrome.

```yaml
ref:
  kind: notes
  properties:
    title: { type: string, source: markdown_frontmatter }
    status: { type: enum, values: [draft, final], source: markdown_frontmatter }
  pane:
    label: Notes
    description: Working notes
    description_body: Notes collected from this project's document sidecars.
    order: 40
    row:
      title: title
      badges: [status]
      secondary: [updated_time]
      list_fields: [tags]
    default_sort:
      - { field: updated_time, direction: desc }
    facets: [status]
    group_by: [status]
    empty_state:
      title: No notes
      body: Nothing matches the current project scope and filters.
```

Constraints that keep the plugin surface bounded:

- `description` is the one-line pane summary and `description_body` is optional expanded
  detail; both feed the Artifacts pane brief.
- Presentation refers only to declared properties or the host common fields (`title`,
  `status`, `project`, timestamps, path/filename).
- List fields are priority hints; detail stays lossless.
- Facets are typed. `group_by` must name groupable fields.
- Unknown optional hints fall back to host defaults. Unknown required constructs degrade
  that one tab visibly and never remove another tab.
- No colors, keybindings, command strings, Python entry points, mutation, or approval
  flows.

`ref.grouping` and `ref.pane.group_by` are alternate spellings; declaring both degrades
the pane. `ref.relations` and `ref.grouping` remain valid beside `ref.pane`.

A `status` property earns `status_counters` automatically. Suppress an earned capability
with `ref.capabilities.suppress: {filter_session: "browse only"}`.

## Visual grammar

Every pane, including Patch and a degraded third-party tab, renders through the shared
shell. The five canonical states, accent rules, relation-panel slot, and grouping
banners are specified in
[Artifacts pane visual grammar](artifacts_pane_visual_grammar.md).

## Relation primitives

The host recognizes three relation kinds:

| Kind        | Use                                                                                     |
| ----------- | --------------------------------------------------------------------------------------- |
| `hierarchy` | Directed parent/child chains. The first declared hierarchy relation owns ancestor keys. |
| `family`    | Undirected sibling sets such as filename families or version families.                  |
| `link`      | Directed references to same-pane or cross-pane targets.                                 |

Each relation declaration has these validated fields:

| Field         | Meaning                                                         |
| ------------- | --------------------------------------------------------------- |
| `name`        | Stable relation id, unique within the pane.                     |
| `kind`        | One of `hierarchy`, `family`, or `link`.                        |
| `label`       | User-facing section label in the relation panel.                |
| `source`      | Declared source property or a host-owned synthetic source name. |
| `target_pane` | Optional Artifacts pane id for cross-pane targets.              |
| `inverse`     | Optional inverse relation id.                                   |
| `directed`    | Whether the edge is one-way.                                    |
| `transitive`  | Whether hierarchy walking may chain through repeated targets.   |

Example provider block:

```yaml
ref:
  relations:
    - name: related
      kind: link
      label: Related
      source: related
      target_pane: null
      inverse: null
      directed: true
      transitive: false
```

The host assigns keys from the compiled relation contract. Providers declare facts; they
do not provide callbacks or key names.

## Grouping declarations

Document providers declare grouping with a default mode and a list of modes:

```yaml
ref:
  grouping:
    default_mode: by_status
    modes:
      - id: by_status
        label: Status
        keys:
          - status
```

The validated `ref.grouping` fields are `default_mode` and `modes`. Each mode accepts
only `id`, `label`, and `keys`; every key must name a declared `ref.properties` field.
The host builds foldable banner rows from those keys and owns the fold registry.

## Reveal lens

Relation navigation first tries to select the target that is already visible. When a
same-pane target exists but the current query hides it, the reveal lens rewrites the
pane query to the narrow relation query for that target and records the original query
and selection. Returning through query history restores the exact previous query and
selection; the lens is derived from the live query, so it does not leave sticky state
behind after the user moves on.

`$` link-follow uses the same lens, but reaches it through a host-owned ordered ladder
rather than a single rewrite: fold expansion, dropping the `limit:` head slice, an
identity-field query, minimal widening, a neutral `limit:all`, and finally targeted
hydration of a row the pane never loaded. See
[The Reveal Ladder](ace.md#the-reveal-ladder) for the user-facing behavior.

## Identity field

Every pane dialect may name one **identity field** — the filterable field an identity
reveal rewrites through to name a single row. The fixed panes use `name` (Patches and
Agents), `id` (Beads and Files), `path` (Plans), and `sha` (Stitches).

A provider does not declare its identity field. Every provider-derived dialect uses
`path`, and the host injects a filterable, exact-match, negatable, searchable `path`
field automatically when `ref.properties` does not already declare one. The compiler
rejects an identity field that is not a declared field or is not filterable, so a
dialect can never advertise a reveal it cannot perform. A dialect with no usable
identity value for a row simply skips that rung and falls through to widening.

## Boundary

A provider can declare relation and grouping facts, but it cannot install commands,
widgets, colors, or key handlers. The host compiles the declaration, enforces action
reachability through `check_app_action`, builds relation indexes from loaded snapshots,
and renders relation panels and grouping banners through shared Artifacts components.
