# 0100 — The licence is MIT

## Context
The blueprint (section 17, D14) named Apache 2.0. Record 0006 left the licence to `project.yaml` and said that the `LICENSE` file is added in the same change that fills the field. The owner has now confirmed MIT.

## Decision
- The licence is **MIT**. `project.yaml` says `licence: "MIT"` and the repository has a `LICENSE` file with the standard MIT text.
- The copyright line of `LICENSE` reads `Copyright (c) [YEAR] [COPYRIGHT HOLDER: ...]`, a marked placeholder: the owner's name is not invented (the author, contact and repository fields of `project.yaml` stay empty for the same reason). The owner fills the line before publishing.
- Blueprint section 17 and D14 are edited to say MIT; this record supersedes the Apache 2.0 choice there. The README names the licence and links `LICENSE`.

## Consequences
- MIT has no explicit patent grant; the owner accepted that by choosing it.
- A test checks that `project.yaml`, `LICENSE` and the README agree.
- UNVERIFIED: that the copyright holder line is filled; it is a placeholder until then.
