---
plan: sdd/tales/202605/pyvision_test_references_1.md
---
 Can you help me make sure that pyvision does not treat references to symbols from test files as acceptable references (i.e. pyvision should fail if the only reference to a symbol is from a test file)? Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
 

%xprompts_enabled:false
### Questions and Answers

#### Q1: Audit remediation

> Pyvision audit surfaced 94 newly-unused public symbols across sase_104. The plan says to pause if the list is unexpectedly large. How should I proceed?

- [ ] **Pause — I will review the list myself** — Stop here. The chezmoi commit is done and the re-vendored script is staged but not committed. I will review the 94 symbols and decide remediations.
- [ ] **Try to delete/privatize the obvious dead code** — Attempt mass remediation in one pass: delete symbols with no callers, privatize those used only locally, and surface any I cannot confidently resolve.
- [ ] **Revert the re-vendor and re-plan** — Roll back the Justfile/AGENTS.md/tools/ changes from pyvendor (leave chezmoi commit intact) so the audit can be tackled separately.
- [x] **Other:** "Record the list of symbols that appeeear to be unused in a new sase artifact."

%xprompts_enabled:true