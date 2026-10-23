# 0150 — Licence holder line and repository address

## Context
Record 0100 chose MIT and left the copyright line of `LICENSE` and the repository address of the README as marked placeholders, so that no personal name is invented. Version 1.0.0 is the point to fill them.

## Decision
- `LICENSE` reads `Copyright (c) 2026 ActuaryCanary contributors`: no personal name, the year of the first release.
- README and guide link to https://github.com/furkzel/ActuaryCanary (clone line, releases page).
- The `author`, `contact` and `repository` fields of `project.yaml` stay empty on purpose.
- This supersedes the placeholder wording of 0100 (lines 8 and 14); the licence itself (MIT) is unchanged.

## Consequences
- No placeholder is left in `LICENSE` or the README.
- UNVERIFIED: that the repository address is the one the owner publishes under.
