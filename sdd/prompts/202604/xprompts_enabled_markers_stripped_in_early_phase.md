---
plan: sdd/tales/202604/xprompts_enabled_markers_stripped_in_early_phase.md
---
We should not run validation on `@` prefixed file references (e.g. checking that the file exists) when those references
are wrapped using the `%xprompts_enabled` directive (see the `sase ace` snapshot below). Can you help me diagnose the
root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill
before making any file changes.

```
Starting agent run
CL: bs_allow_model
Workspace: /google/src/cloud/bbugyi/bs_allow_100/google3
Workflow: ace(run)-260417_181237

=== Prompt ===
#hg:bs_allow_model

Apply the following code review changes to the codebase. Make each change as described,
run any relevant tests, and commit your changes.

%xprompts_enabled:false
### Change 1: aaa_structure (suggestion)
**File**: `contentads/drx/fe/client/inventory/protections/service/test/manual_creative_review_protection_converter_test.dart:33`
Remove this blank line. Since each section in this test method contains only one top-level statement, blank lines between sections are not necessary. Additionally, the current formatting is inconsistent as there is a blank line between Arrange and Act, but no blank line between Act and Assert.

### Change 2: symbol_names (suggestion)
**File**: `contentads/drx/fe/client/inventory/protections/components/detail/ad_content/lib/advertiser_brand_detail_panel.dart:82`
Consider using more inclusive language for these new public @Input() fields. Suggest renaming 'blacklistLabelOverride' to 'blocklistLabelOverride' and 'whitelistLabelOverride' to 'allowlistLabelOverride' to align with Google's inclusive language guidelines (go/inclusive-language).

### Change 3: symbol_names (suggestion)
**File**: `contentads/drx/fe/client/inventory/protections/components/detail/ad_content/lib/advertiser_brand_detail_panel.dart:243`
Rename the internal default label constants to use inclusive language, e.g., '_defaultBlocklistLabel' and '_defaultAllowlistLabel'.

### Change 4: visibility (suggestion)
**File**: `contentads/drx/fe/client/inventory/protections/components/detail/ad_content/lib/advertiser_brand_detail_panel.dart:87`
The 'blacklistLabel' and 'whitelistLabel' getters are only accessed within the component's template. To clarify their usage and scope, they should be marked with the '@visibleForTemplate' annotation.
%xprompts_enabled:true

#commit(who=mentor)
==============

=== Dynamic Memory ===
  + memory/long/aaa_test_structure  (matched: test, tests)
  + memory/long/golinks_reference  (matched: go/)
  + memory/long/ui_style  (matched: dart)
======================


❌ ERROR: The following file(s) referenced in the prompt do not exist:
  - @Input
  - @visibleForTemplate

⚠️ File validation failed. Terminating workflow to prevent errors.

Workspace released
```
