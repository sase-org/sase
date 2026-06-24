---
plan: sdd/tales/202606/fix_rust_fmt_check_directive.md
---
 GitHub Actions is failing with the below error. Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
  
```
Diff in /home/runner/work/sase/sase/sase-core/crates/sase_core/src/editor/directive.rs:337:
         // ... but neither is advertised in completion. `%approve` matches no
         // advertised directive; `%a` only surfaces `%alt` (the lone directive
         // whose name starts with `a`), never `%approve`/`%plan`.
-        assert!(
-            build_directive_completion_candidates("%approve")
-                .candidates
-                .is_empty()
-        );
+        assert!(build_directive_completion_candidates("%approve")
+            .candidates
+            .is_empty());
         let a_completions = build_directive_completion_candidates("%a");
         let a_names: Vec<&str> = a_completions
             .candidates
error: Recipe `rust-fmt-check` failed on line 412 with exit code 1
Error: Process completed with exit code 1.
```