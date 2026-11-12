# 0401 — Index clause: payment by payment, and the occurrence-date setting for the generator's truth

## Context
CV09 0.2.0 approximated the index clause with the paid-weighted average payment month of a claim (record 0202). The owner decided on 2026-11-12 for a payment-by-payment clause. The generator uses another clause: it fixes a claim's retention and limit at the price level of its occurrence date (record 0240).

## Decisions
- **Setting `index_clause`**, one per run and independent of the treaty: `payment_by_payment` (default, the owner's choice) or `occurrence_date` (the generator's clause). It is a parameter of the run, so it enters the parameter rows and the run id. The report names the clause in use beside every indexed treaty (the section notes).
- **Payment by payment.** A treaty with `index_series` states R and L at the price level of its inception month. A payment p_j made in month t_j is deflated, p'_j = p_j · I(inception) / I(t_j); the layer is applied to the cumulative deflated payments of the claim (or event); the ceded increment c'_j = layer(cum'_j) − layer(cum'_{j−1}) is inflated back, c_j = c'_j · I(t_j) / I(inception). A payment is the change of paid between two valuation rows of a claim, dated at the later row: the data hold cumulative amounts per valuation date, so the month of the valuation at which paid moved stands for the payment month (monthly valuations in the generated data, so the month is exact there).
- **Reserves.** The case reserve at a valuation date is valued with the index of that date: ceded reserve = (layer(cum' + reserve · d) − layer(cum')) / d with d = I(inception)/I(valuation). It is an approximation of a future payment and is labelled so in the section notes and the report.
- **Events.** The event's payments of a month are deflated and summed; the event's ceded paid at a date is shared among its claims in proportion to their paid (CV09); a test proves that two claims of one event cede together what one claim with their summed payments cedes.
- **Occurrence date.** R and L of a claim are R · I(occurrence) / I(inception) (an event: the earliest occurrence date of its claims in the section); no deflation. The generator writes the terms at the price level of the contract period's start, round(R0 · f(inception), 2), and applies R0 · f(occurrence), with f its monthly index over the base value (`synthetic/market.py`, `ri_feeds.py`). The market feed publishes the same monthly index, so R_table · I(occ)/I(inception) = R0 · f(occ) up to the rounding of the table to cents (relative difference at most 0.005 / R_table, below 1e-7 for the retentions of the scenarios).
- **Surplus.** An indexed surplus line is taken at the price level of the policy start in both settings, r · I(start)/I(inception), as the generator does: a surplus share is fixed when the risk is written, so no payment-by-payment reading exists for it.
- **Index of a date.** The value of the series in that calendar month, or the latest month before it (first value before the series starts). Stop loss is not indexed (its terms are loss ratios).
- **Missing series.** A treaty whose `index_series` is not a PRICE_INDEX series of market is applied without indexation and the note says so (DV-RTY-10).

## Consequences
- CV09 0.3.0 replaces the approximation rule with this clause; record 0202's index line is superseded.
- Hand cases (fixture MT21): a claim with three payments in months of index 110, 120 and 125 under both settings, and a claim whose layer is exhausted by one payment; exact to 1e-12.
- The ground-truth test reproduces the generator with `occurrence_date`; under the default the difference on the indexed layers is measured (record 0403).
