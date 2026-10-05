---
name: parity
description: End-to-end named-input-type fixture (inline enum, effort, model, plugin).
input:
  env:
    type: enum
    choices:
      - { value: staging, description: Pre-prod cluster }
      - { value: prod, label: Production, description: Customer traffic }
    default: staging
  model:
    type: model
    default: "@large"
  effort:
    type: effort
    default: medium
  edition:
    type: sase-research-artifacts@audio_edition
    default: brief
---

env={{ env }} model={{ model }} effort={{ effort }} edition={{ edition }}
