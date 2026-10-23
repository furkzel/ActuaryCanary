# MT07 Inflation-adjusted chain ladder

Specification: [MT07](../../spec/methods/MT07-inflation-adjusted-chain-ladder.yaml) · Decisions: [0012](../decisions/0012-inflation-adjusted-basis.md), [0042](../decisions/0042-inflation-adjusted-timing.md), [0044](../decisions/0044-inflation-adjusted-ground-truth.md), [0063](../decisions/0063-inflation-adjusted-exceptions-are-process-variance.md), [0075](../decisions/0075-mt06-and-mt07-ground-truth-amendments.md)

## Purpose

In a high-inflation market the nominal chain ladder confuses two things: claims that take time to be paid, and prices that rise while they wait. Its factors then carry past inflation, and applying them to the future silently assumes the same inflation again. MT07 removes the price effect: the paid triangle is restated to the prices of one date, the chain ladder runs on that, and any future inflation enters only as an explicit, recorded assumption.

## Theory

Each paid flow $\Delta P_k(v_n)$ of a claim in month $v_n$ is converted to the reporting currency at its own rate and restated to the value date $t_{\mathrm{value}}$ with the price index $I$:

$$X^{\mathrm{adj}}_{i,j} = \sum_{k \in i} \sum_{v_n \in (i,j)} \Delta P_k(v_n) \frac{I(t_{\mathrm{value}})}{I(v_n)}, \qquad C^{\mathrm{adj}}_{i,j} = \sum_{l \le j} X^{\mathrm{adj}}_{i,l}$$

The chain ladder of [MT02](MT02-chain-ladder.md) on this triangle gives $\hat U^{\mathrm{adj}}_i = C^{\mathrm{adj}}_{i,J_i} \cdot CDF^{\mathrm{adj}}_{J_i}$ and the projected future payments $\hat X^{\mathrm{adj}}_{i,k} = \hat C^{\mathrm{adj}}_{i,k} - \hat C^{\mathrm{adj}}_{i,k-1}$ at value-date prices. With an assumed annual future inflation $\pi$, each future payment is placed at the middle of its development period, $t(i,k)$, and re-inflated:

$$\hat X^{\mathrm{nom}}_{i,k} = \hat X^{\mathrm{adj}}_{i,k} (1+\pi)^{(t_{i,k} - t_{\mathrm{value}})/365.25}, \qquad \hat U^{\mathrm{nom}}_i = P_i(c) + \sum_{k > J_i} \hat X^{\mathrm{nom}}_{i,k}$$

where the exponent is the time in years from the value date to $t_{i,k}$ and $P_i(c)$ is the nominal paid at the cut-off $c$. Without a future inflation assumption the platform gives results at value-date prices only and says so; it never invents one.

## Assumptions and how to check them

| Assumption | Check |
| --- | --- |
| The chosen index reflects claims inflation of the line. | Compare inflation-adjusted severity (CL06) across origins; a residual trend is superimposed inflation the index misses. |
| Development in real terms is stable. | As for [MT02](MT02-chain-ladder.md), on the adjusted triangle. |
| Future payments of a development period fall at its middle. | None: a convention, stated in the report. |

## In the platform

`canary run --value inflation-adjusted [--value-date YYYY-MM-DD] [--price-index SERIES]` runs the adjusted basis; the price index comes from the market file (default series from `project.yaml`). The method does not run when the series is missing or does not cover the triangle. Future inflation is set in the assumptions register (`--assumptions`). The expected payments by calendar period are written to `cash_flows.csv`. Version 1.0 has no IBNR on this basis (no incurred at value-date prices) and a tail of 1.0, which leaves out a small share of the ultimate of a long-tailed line (decision 0063).

## Worked example

<!-- worked-example:begin (written by docs/tools/worked_examples.py; do not edit) -->

An illustration, not data: the paid triangle of the hand fixture is read as nominal amounts and the price index is assumed to grow 20 per cent a year, with year-end values 2021: 100, 2022: 120, 2023: 144, 2024: 172.8. To keep the arithmetic by hand, each year's payments are taken at the index of that year end; the platform uses the month of each payment (CV02).

Each cell is the sum of its incremental payments times $I(2024)/I(\text{year paid})$. Paid triangle at 2024 prices:

| Origin | 12 months | 24 months | 36 months | 48 months |
| --- | --- | --- | --- | --- |
| 2021 | 155.52 | 270.72 | 306.72 | 326.72 |
| 2022 | 158.4 | 278.4 | 324.4 |  |
| 2023 | 120 | 210 |  |  |
| 2024 | 130 |  |  |  |

Age-to-age factors, nominal against adjusted (the inflation of the later development years is gone from the adjusted ones):

| Basis | 12-24 months | 24-36 months | 36-48 months |
| --- | --- | --- | --- |
| Nominal | 1.9 | 1.2 | 1.1 |
| Adjusted | 1.7494 | 1.1493 | 1.0652 |

Ultimate at 2024 prices, and with a future inflation assumption of 20 per cent a year (each future payment re-inflated from the middle of its development year):

| Origin | Paid at 2024 prices | Ultimate at 2024 prices | Unpaid at 2024 prices | Nominal unpaid | Nominal ultimate | Nominal chain ladder ultimate |
| --- | --- | --- | --- | --- | --- | --- |
| 2021 | 326.72 | 326.72 | 0 | 0 | 220 | 220 |
| 2022 | 324.4 | 345.5528 | 21.1528 | 23.1703 | 279.1703 | 281.6 |
| 2023 | 210 | 257.0974 | 47.0974 | 55.0346 | 245.0346 | 250.8 |
| 2024 | 130 | 278.4341 | 148.4341 | 178.2339 | 308.2339 | 326.04 |

The nominal chain ladder carries the past inflation into the future payments implicitly; the adjusted method makes the inflation an explicit and changeable assumption.

<!-- worked-example:end -->

## References

- Taylor, G. (2000). *Loss Reserving: An Actuarial Perspective*. Kluwer.
- Friedland, J. *Estimating Unpaid Claims Using Basic Techniques*. Casualty Actuarial Society, chapter 11.
