# 0055 — The tier A methods in the reserving module

## Context
P08 built MT03 to MT10 as pure functions on arrays and left the call to the integration. M04 ran the chain ladder only. The owner asked that the methods run per segment and line on the chosen basis, with P08's defaults, and that every judgement goes through the assumptions register (0037).

## Decision
- Per segment and line, on the paid and on the incurred triangle: chain ladder through the register (`chain_ladder_judged`), Cape Cod, Bornhuetter–Ferguson and the expected loss ratio when earned premium is present, and the Mack standard error. On the paid triangle also MT07; the selection (MT10) is made on the incurred triangle, its default (spec parameter `measure`).
- Premium per origin is PR02 on the basis of the run, taken from the measure engine and matched to the origins by label (`modules/premium_input.py`). It is built for accident origins. For underwriting origins premium by policy start period is not built, so the premium-based methods say so (`UNDERWRITING_PREMIUM`); for report and first-valuation origins they refuse as MT03 to MT05 specify. A missing premium file, policies file or conversion gives the reason of PR02.
- Priors are the register's entries, else the Cape Cod ratio of the same triangle labelled data-derived (0011); with paid and incurred triangles that gives one prior per triangle.
- MT07 needs the same claims restated and not restated. The pipeline builds the paid triangles on the other value basis (adjusted when the run is nominal, nominal when it is adjusted), only when the market data holds the price index; otherwise MT07 says why it did not run. It uses the run's chain-ladder settings and the tail factor of the paid chain ladder; register entries for cells and factors of MT02 do not apply to it. Its future inflation is the register's MT07 entry, default none (0012): results at value-date prices, nominal columns empty.
- Mack always fits its own chain ladder (0041); RS03 applies its coefficient of variation to the selected reserve, per origin and in total, on both triangles.
- A method that cannot run keeps its reason; M04 is `limited` and says for how many triangles. Methods that exist are listed as built.

## Consequences
- The 4 x 4 triangles of the tiny baseline are too small for Mack (0041): M04 is limited there, and ran on baseline medium.
- Selected factors, exclusions and tails of the register apply to the paid and incurred chain ladder by scope (`group/measure`); MT07 follows only the tail.
- The extra triangle build costs about a second on baseline medium.
