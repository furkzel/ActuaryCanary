# 0006 — Licence comes from project.yaml

## Context
The licence is not decided yet (`licence: ""` in `project.yaml`, listed under open decisions in `HANDOVER.md`). A wrong licence is hard to undo once others use the code.

## Decision
`project.yaml` is the single source for the licence, like the other metadata. While it is empty, no `LICENSE` file exists and the README says the licence is not yet chosen. When the owner fills the field, the matching `LICENSE` file is added in the same change.

## Consequences
- The repository is all-rights-reserved by default until then.
- `canary info` omits empty metadata fields.
