---
plan: sdd/tales/202605/bead_backend_clippy.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix
it? This is the bead-backend job that is failing. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
 

```
error: unnecessary `if let` since only the `Some` variant of the iterator element is used
   --> crates/sase_core/src/artifact/ingest.rs:109:9
    |
109 | /         for maybe_path in [
110 | |             resolved.projects_root.as_deref(),
111 | |             resolved.workspace_root.as_deref(),
112 | |             resolved.beads_dir.as_deref(),
...   |
125 | |         }
    | |_________^
    |
help: try `.flatten()` and remove the `if let` statement in the for loop
   --> crates/sase_core/src/artifact/ingest.rs:115:13
    |
115 | /             if let Some(path) = maybe_path {
116 | |                 let request = ArtifactPathUpsertRequestWire {
117 | |                     kind: Some(ARTIFACT_KIND_DIRECTORY.to_string()),
118 | |                     provenance: Some(ARTIFACT_PROVENANCE_DERIVED.to_string()),
...   |
123 | |                 mutations.merge(artifact_upsert_path(store, path, request)?);
460 ~         ].into_iter().flatten() {
461 +             if path.exists() {
462 +                 ids.insert(path_to_artifact_id(path));
463 +             }
464 +         }
    |

error: writing `&String` instead of `&str` involves a new object where a slice will do
    --> crates/sase_core/src/artifact/ingest.rs:2125:21
     |
2125 | fn non_empty(value: &String) -> Option<String> {
     |                     ^^^^^^^
     |
     = help: for further information visit https://rust-lang.github.io/rust-clippy/rust-1.95.0/index.html#ptr_arg
     = note: `-D clippy::ptr-arg` implied by `-D warnings`
     = help: to override `-D warnings` add `#[allow(clippy::ptr_arg)]`
help: change this to
     |
2125 ~ fn non_empty(value: &str) -> Option<String> {
2126 |     if value.trim().is_empty() {
2127 |         None
2128 |     } else {
2129 ~         Some(value.to_owned())
     |

error: use of `unwrap_or_else` to construct default value
    --> crates/sase_core/src/artifact/ingest.rs:3060:44
     |
3060 |         metadata: request.metadata.clone().unwrap_or_else(Map::new),
     |                                            ^^^^^^^^^^^^^^^^^^^^^^^^ help: try: `unwrap_or_default()`
     |
     = help: for further information visit https://rust-lang.github.io/rust-clippy/rust-1.95.0/index.html#unwrap_or_default
     = note: `-D clippy::unwrap-or-default` implied by `-D warnings`
     = help: to override `-D warnings` add `#[allow(clippy::unwrap_or_default)]`

error: could not compile `sase_core` (lib) due to 4 previous errors
warning: build failed, waiting for other jobs to finish...
error: could not compile `sase_core` (lib test) due to 4 previous errors
error: Recipe `rust-clippy` failed on line 288 with exit code 101
Error: Process completed with exit code 101.
```