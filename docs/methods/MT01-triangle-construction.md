# MT01 Triangle construction

Specification: [MT01](../../spec/methods/MT01-triangle-construction.yaml) · Decisions: [0008](../decisions/0008-origins-and-development-grid.md), [0024](../decisions/0024-triangle-choices-not-fixed-by-the-specs.md), [0033](../decisions/0033-bases-on-triangles.md)

## Purpose

Every reserving method starts from a triangle: how much was paid, reported or still reserved for the claims of each origin period, seen at successive ages. MT01 builds paid, incurred, case-reserve and claim-count triangles from the claim valuations (one row per claim and valuation date), for any origin and development period and on any basis (gross, ceded or net; nominal or inflation-adjusted). It never mixes segments: one set of triangles per segment and line.

## Theory

Each claim gets one origin period $i$ (by default its accident period) and a group. A valuation point is a month end, spaced by the development period $L_d$ months back from the cut-off $c$. The position of a claim at a valuation point $v$ is its last row on or before $v$ (the as-of rule), so a missing month or a closed claim is carried forward:

$$x_k(v) = x_k\big(\max\{v_n \le v\}\big)$$

The cumulative cell of origin $i$ at development index $j$ is the sum over the claims of that origin, taken at the valuation point $v(i,j)$ where the origin has that index:

$$C_{i,j} = \sum_{k:\ \mathrm{origin}(k) = i} x_k\big(v(i,j)\big), \qquad X_{i,0} = C_{i,0},\quad X_{i,j} = C_{i,j} - C_{i,j-1}$$

Cells whose valuation point lies after the cut-off are future and stay empty; the last observed cell of each origin is the latest diagonal. Amounts are converted to the reporting currency with one constant rate per currency (nominal basis) or at the rate and price index of each payment's own date (inflation-adjusted basis, which MT07 uses).

## Assumptions and how to check them

- *Each claim has one origin period, fixed for the run.* Check the quality findings on the origin dates (DV-CLM-03, DV-CLM-07); claims that fail are listed and left out.
- *Valuation rows describe the claim as known at their date.* Check that paid never decreases (DV-CLV-07) and that duplicate rows are resolved (DV-CLV-06).
- Cells with fewer than five claims, negative incremental cells and origins whose date is a first-valuation proxy are marked in the diagnostics.

## In the platform

`canary run` builds the triangles for every group and basis the run asks for (`--origin-axis`, `--origin-period`, `--development-period`, `--basis`, `--value`). Without a claims file the first valuation date stands in for the accident date and the report labels the triangles as proxy (decision 0008).

## Worked example

<!-- worked-example:begin (written by docs/tools/worked_examples.py; do not edit) -->

Three claims of one line (the fixture of the MT01 test, worked by hand there). Claim A has no row for April 2023, closes in December 2023, reopens in August 2024 and closes again; B is reported in January 2024; C occurs in 2024. Cut-off 2025-06-30.

| Claim | Valuation date | Paid to date | Case reserve | Status |
| --- | --- | --- | --- | --- |
| A | 2023-02-28 | 0 | 100 | OPEN |
| A | 2023-03-31 | 20 | 80 | OPEN |
| A | 2023-05-31 | 50 | 60 | OPEN |
| A | 2023-06-30 | 50 | 60 | OPEN |
| A | 2023-12-31 | 120 | 0 | CLOSED |
| A | 2024-08-31 | 120 | 30 | REOPENED |
| A | 2025-01-31 | 160 | 0 | CLOSED |
| B | 2024-01-31 | 0 | 200 | OPEN |
| B | 2024-06-30 | 70 | 150 | OPEN |
| B | 2025-03-31 | 210 | 40 | OPEN |
| C | 2024-07-31 | 10 | 40 | OPEN |
| C | 2025-06-30 | 30 | 20 | OPEN |

Cumulative paid, annual origins and annual development counted back from the cut-off (ages 6, 18 and 30 months, because the cut-off falls mid-year):

| Origin | 6 months | 18 months | 30 months |
| --- | --- | --- | --- |
| 2023 | 50 | 190 | 370 |
| 2024 | 0 | 30 |  |
| 2025 | 0 |  |  |

Incremental paid (each cell minus the one to its left):

| Origin | 6 months | 18 months | 30 months |
| --- | --- | --- | --- |
| 2023 | 50 | 140 | 180 |
| 2024 | 0 | 30 |  |
| 2025 | 0 |  |  |

Cumulative incurred (paid plus case reserve, as known at each valuation point):

| Origin | 6 months | 18 months | 30 months |
| --- | --- | --- | --- |
| 2023 | 110 | 340 | 410 |
| 2024 | 0 | 50 |  |
| 2025 | 0 |  |  |

How one cell is built: origin 2023 at 18 months is the position at 2024-06-30. Claim A has no row on that day, so its last row (December 2023, closed) is carried forward: paid 120; claim B has paid 70; the cell is 120 + 70 = 190. Claim C belongs to origin 2024.

<!-- worked-example:end -->

## References

- Friedland, J. *Estimating Unpaid Claims Using Basic Techniques*. Casualty Actuarial Society, chapters 3 and 5.
