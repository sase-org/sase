# Artifacts pane contract

`ArtifactsPaneContract` is the host-owned record that decides what a pane can do before
widgets, keybindings, or document providers run. Built-in panes compile the contract
from `_artifact_tab_contract_adapters.py`; schema-v1 document providers compile it from
their `ref` declaration.

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

## Boundary

A provider can declare relation and grouping facts, but it cannot install commands,
widgets, colors, or key handlers. The host compiles the declaration, enforces action
reachability through `check_app_action`, builds relation indexes from loaded snapshots,
and renders relation panels and grouping banners through shared Artifacts components.
