# 0205 — Life data and study conventions

## Context
Blueprint 4.4 lists the life and pension feeds and allows age only as a band, with no birth dates. Experience studies need an age that moves with time, an exposure definition and a choice of cells.

## Decision (proposed, draft, CV11 and the life concepts)
- **Age.** `age_band` holds a whole-year age or a band, on the source's own definition: age last birthday (default) or age nearest birthday, set in the mapping profile. Birth dates are never read. Age moves on policy anniversaries from the entry age implied by the first valuation. This is exact for insurance age at entry and otherwise up to one year off, which the report states.
- **Exposure.** Central exposure by default. A q-table rate becomes a constant force over the year of age, mu = -ln(1 - q). Initial exposure is an option.
- **Cells.** Calendar years by default, always split by age and policy year (policy year 1 is the first).
- **Events.** Exits are dated by life_events, or at the middle of the interval between valuations, labelled. The last 3 months before the cut-off are left out of mortality studies because deaths are reported late.
- **Transfers.** TRANSFER_IN and TRANSFER_OUT are fund flow types (beyond blueprint 4.4), so that LF04 sees the money of transfers. The life event keeps the event itself.
- **Sex** is optional, off by default, and aggregated only.
- **MT19** is claims only, because a spec lists one set of required fields. Life persistency carries its own product-limit formula (LF03), so M11 runs on life data alone. A Cox model of lapse is not specified in this round.

## Consequences
- The default reference tables are still an open decision (blueprint 18.2). Without a table, M11 shows crude rates.
- The health segment stays open: `life_in_force` and M11 name it as requiring a decision.
