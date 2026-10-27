# 0622 — The module specifications and the method notes are not changed by the integration

## Context
The handovers of P24 and P25 say that M04 "gains" MT12 to MT16, M03 gains MT17 and MT19, M06 gains MT18, and that the method notes come with the report item. The work item of the integration allows no change of a specification except the `implemented` flags, and the modules M03, M04 and M06 are `reviewed`.

## Decision
- The `methods` lists of M03, M04 and M06 are left as they are (versions 1.0.0, 1.0.0 and 1.1.0). The methods are wired in code (0620, 0621); a module outcome lists the methods of its spec that are built, so the lists name what they named before, and the tier B methods appear in the manifest (`specs`), in the notes of the module when they refuse, and in the output files.
- AE02 stays out of every module until M12 and M13 are built.
- The test that every implemented method has a note under `docs/methods/` is limited to tier A. The notes of MT11 to MT18 and MT22 are written by P27, with the report pages.

## Consequences
- If the owner wants the lists amended now, it is one version bump per module (M03 1.1.0 with MT17, M04 1.1.0 with MT11 to MT16 and MT22, M06 1.2.0 with MT18) and a regeneration of the goldens and the examples; no code changes.
