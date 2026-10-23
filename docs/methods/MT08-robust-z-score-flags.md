# MT08 Robust z-score anomaly flags

Specification: [MT08](../../spec/methods/MT08-robust-z-score-flags.yaml) · Decisions: [0043](../decisions/0043-anomaly-methods.md), [0057](../decisions/0057-anomaly-flags-in-the-run.md), [0060](../decisions/0060-robust-z-incurred-change-at-payment.md)

## Purpose

Find individual payments and reserve movements that lie far from what is normal for their line, so that a person can look at them: a mistyped amount, a duplicated payment, a reserve set in the wrong currency. A plain z-score is distorted by the very outliers it should find (they inflate the mean and the standard deviation). The robust version uses the median and the median absolute deviation, which a few extreme values cannot move.

## Theory

Three variables are scored, each on the log scale, in the reporting currency at a constant rate, within each segment and line:

- `paid_flow`: $y = \ln(\Delta P)$ for each positive paid flow;
- `reserve_change`: $y = \ln\frac{R(v_n) + 1}{R(v_{n-1}) + 1}$ for consecutive rows with a reserve;
- `incurred_change_at_payment`: $y = \ln\frac{I^+(v_n) + 1}{I^+(v_{n-1}) + 1}$ with $I = P + R$, on rows where a positive payment was made and incurred moved, that is a payment the case reserve did not absorb.

With $\tilde y$ the median of the group and $\mathrm{MAD} = \mathrm{median}\,|y - \tilde y|$, the robust z-score and the flag rule are

$$z = \frac{0.6745\,(y - \tilde y)}{\mathrm{MAD}}, \qquad \text{flag if } |z| > 3.5$$

The constant 0.6745 makes $z$ comparable to an ordinary z-score for normal data, and 3.5 is the cut-off recommended by Iglewicz and Hoaglin (1993). When the MAD is zero (many unchanged values), the mean absolute deviation replaces it, $z = (y - \tilde y)/(1.253314 \cdot \mathrm{mean}\,|y - \tilde y|)$; when both are zero nothing is flagged.

## Assumptions and how to check them

| Assumption | Check |
| --- | --- |
| Anomalies are rare, so median and MAD describe normal behaviour. | The share of flagged values per group stays below a few per cent. The platform warns above 5 per cent: the group may mix populations (for example two currencies) and its flags are leads, not errors. |
| On the log scale the variables are roughly symmetric. | The histogram of the log values per group. |

Groups with fewer than 30 values are not scored.

## What a flag is

A flag is a lead to review, never a verdict. Each carries the claim, the date, the source row of the input file, the value, $z$ and the threshold, in words. On the synthetic data the injected extreme payments are 20 to 50 times the median payment, inside the spread of the log payments, so `paid_flow` alone found none of them; `incurred_change_at_payment` was added for that reason and recalls them (decision 0060). The variable `reserve_change` flags a large share of the case-reserve movements of motor own-damage on the synthetic data, because the MAD is zero on unchanged months; the warning says so.

## Worked example

<!-- worked-example:begin (written by docs/tools/worked_examples.py; do not edit) -->

The fixture of the MT08 specification: 31 payments of one group whose logarithms are the whole numbers 1 to 30 and one payment whose logarithm is 60 (a payment of $e^{60}$ amid payments of $e^1$ to $e^{30}$; the numbers are chosen for easy arithmetic, not for realism).

| Quantity | Value |
| --- | --- |
| Median of the log values | 16 |
| Median absolute deviation (MAD) | 8 |
| z of the payment with log 1 | -1.2647 |
| z of the payment with log 30 | 1.1804 |
| z of the payment with log 60 | 3.7098 |
| Threshold | 3.5 |

$z = 0.6745 \times (60 - 16) / 8 = 3.7098$, above 3.5, so exactly one payment is flagged: claim C030, source row 32, with its z and the threshold in the flag's text. The next largest payment has a z of 1.18.

<!-- worked-example:end -->

## References

- Iglewicz, B. and Hoaglin, D. C. (1993). *How to Detect and Handle Outliers*. ASQC Quality Press.
