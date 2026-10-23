# MT06 Mack standard error with lognormal range

Specification: [MT06](../../spec/methods/MT06-mack.yaml) · Decisions: [0041](../decisions/0041-mack-conventions.md), [0045](../decisions/0045-mack-coverage-test.md), [0062](../decisions/0062-mack-coverage-is-a-property-of-the-data.md), [0075](../decisions/0075-mt06-and-mt07-ground-truth-amendments.md)

## Purpose

A reserve estimate without a range invites false confidence. Mack (1993) gives the standard error of the chain-ladder reserve without assuming a distribution: for each origin and for the total. The platform turns it into percentiles, value at risk and tail value at risk by assuming a lognormal reserve, an approximation that every output labels.

## Theory

The model assumes, for the cumulative claims $C_{i,j}$ of origin $i$:

1. $E[C_{i,j+1} \mid C_{i,0}, \dots, C_{i,j}] = f_j \, C_{i,j}$ (development proportional to the current level),
2. origins are independent,
3. $\mathrm{Var}[C_{i,j+1} \mid C_{i,0}, \dots, C_{i,j}] = \sigma_j^2 \, C_{i,j}$.

The chain ladder ([MT02](MT02-chain-ladder.md)), volume-weighted over all diagonals and with no tail, estimates $f_j$. The variance parameter of a column with $n_j$ link ratios is

$$\hat\sigma^2_j = \frac{1}{n_j - 1} \sum_{i \in A_j} C_{i,j} \big(F_{i,j} - f_j\big)^2$$

A column with fewer than two link ratios (normally the last) is extrapolated from the two before it, $\hat\sigma^2_{j} = \min\big(\hat\sigma^4_{j-1}/\hat\sigma^2_{j-2},\ \hat\sigma^2_{j-1},\ \hat\sigma^2_{j-2}\big)$. With $S_k = \sum_{i \in A_k} C_{i,k}$, the mean squared error of the reserve $\hat R_i$ of origin $i$, and of the total, are

$$\widehat{\mathrm{mse}}(\hat R_i) = \hat U_i^2 \sum_{k=J_i}^{J-2} \frac{\hat\sigma^2_k}{f_k^2} \Big( \frac{1}{\hat C_{i,k}} + \frac{1}{S_k} \Big)$$

$$\widehat{\mathrm{mse}}(\hat R) = \sum_i \widehat{\mathrm{mse}}(\hat R_i) + 2 \sum_{i < l} \hat U_i \hat U_l \sum_{k=\max(J_i, J_l)}^{J-2} \frac{\hat\sigma^2_k / f_k^2}{S_k}$$

The standard error is $se = \sqrt{\widehat{\mathrm{mse}}}$ and the coefficient of variation $cv = se / \hat R$. The first term of the origin formula is process variance (the claims themselves are random), the second is parameter variance (the factors are estimated); the covariance term of the total arises because all origins use the same estimated factors.

For the range, a lognormal with the same mean $R$ and standard error:

$$\sigma^2 = \ln\big(1 + (se/R)^2\big), \qquad \mu = \ln R - \sigma^2 / 2, \qquad q_p = e^{\mu + \sigma z_p}, \qquad \mathrm{TVaR}_p = e^{\mu + \sigma^2/2} \frac{\Phi(\sigma - z_p)}{1 - p}$$

The platform shows the 50, 75, 90, 95, 99 and 99.5 per cent percentiles, VaR at 99.5 per cent (the one-in-200 calibration) and TVaR at 99 per cent. When the selected ultimate ([MT10](MT10-ultimate-selection.md)) is not the chain ladder, the coefficient of variation is applied to the selected reserve and the result is labelled "Mack CV applied to selected reserve".

## Assumptions and how to check them

| Assumption | Check |
| --- | --- |
| Development is proportional to the current cumulative. | Plot $C_{i,j+1}$ against $C_{i,j}$ per column; the relation should pass through the origin. |
| Origins are independent. | No calendar-diagonal pattern in the standardised residuals (the report draws them by origin, development and diagonal). |
| Variance is proportional to the current cumulative. | The residuals show no fan shape against $C_{i,j}$. |
| The reserve is lognormal. | Not testable on one triangle. |

**Where the range is too narrow.** Calendar-year inflation, development beyond the last observed age and shocks that hit one origin break the independence assumption. On the synthetic baseline the 95th percentile covered the true reserve less often than 95 per cent on such lines (decision 0062 gives the figures per line); the report says that Mack ranges on inflation-driven or long-tailed lines are too narrow. On triangles drawn from Mack's own model the calibration holds (coverage inside 90–99 per cent, slow test behind `ACTUARYCANARY_MONTE_CARLO=1`).

## In the platform

The method needs at least three development columns whose variance can be estimated, so it does not run on a 4 × 4 triangle; the report says why when a group has too few origins. With fewer than eight origin periods the diagnostics warn of thin evidence.

## Worked example

<!-- worked-example:begin (written by docs/tools/worked_examples.py; do not edit) -->

The 4 x 4 hand fixture is too small for the Mack model: it needs variance estimates from at least three development columns that have two or more link ratios, and the hand triangle has two such columns. The example therefore uses the 10 x 10 GenIns triangle (Taylor and Ashe, 1983, the triangle of Mack, 1993) from `tests/benchmarks/genins/`, whose standard errors the tests compare with the chainladder package to six significant figures.

Reserve (chain-ladder ultimate minus latest cumulative), Mack standard error and coefficient of variation per origin (origin 2001 is fully developed):

| Origin | Reserve | Standard error | CV |
| --- | --- | --- | --- |
| 2002 | 94,634 | 75,535 | 0.798 |
| 2003 | 469,511 | 121,699 | 0.259 |
| 2004 | 709,638 | 133,549 | 0.188 |
| 2005 | 984,889 | 261,406 | 0.265 |
| 2006 | 1,419,459 | 411,010 | 0.29 |
| 2007 | 2,177,641 | 558,317 | 0.256 |
| 2008 | 3,920,301 | 875,328 | 0.223 |
| 2009 | 4,278,972 | 971,258 | 0.227 |
| 2010 | 4,625,811 | 1,363,155 | 0.295 |
| Total | 18,680,856 | 2,447,095 | 0.131 |

Variance parameters $\hat\sigma^2_j$ by column: 160,280.3, 37,736.9, 41,965.2, 15,182.9, 13,731.3, 8,185.8, 446.6, 1,147.4, 446.6 (the last is extrapolated with the rule of the specification).

Lognormal step for the total: $\sigma^2 = \ln(1 + (2,447,095 / 18,680,856)^2) = 0.01701$ and $\mu = \ln R - \sigma^2/2 = 16.7345$. The percentiles of the total reserve:

| Percentile | Total reserve |
| --- | --- |
| 50.0% | 18,522,611 |
| 75.0% | 20,226,048 |
| 90.0% | 21,892,743 |
| 95.0% | 22,955,180 |
| 99.0% | 25,089,172 |
| 99.5% | 25,919,050 |

Value at risk at 99.5%: 25,919,050. Tail value at risk at 99%: 26,245,103. These two use the lognormal approximation, which the report labels as such.

<!-- worked-example:end -->

## References

- Mack, T. (1993). Distribution-free calculation of the standard error of chain ladder reserve estimates. *ASTIN Bulletin* 23.
- England, P. D. and Verrall, R. J. (2002). Stochastic claims reserving in general insurance. *British Actuarial Journal* 8.
- Taylor, G. C. and Ashe, F. R. (1983). Second moments of estimates of outstanding claims. *Journal of Econometrics* 23 (the origin of the GenIns triangle).
