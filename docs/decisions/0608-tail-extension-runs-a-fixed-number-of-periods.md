# 0608 — Tail factor: the extension runs a fixed number of periods

## Context
Record 0276 found that the package multiplies 100 extension periods while MT14 stopped the product when f − 1 fell below 1e-4. The two differ for RAA: the inverse power tail is 1.1015 with the package rule and 1.0991 with the stopping rule (68 periods before the stop), the exponential tail 1.00944 against 1.00922. The stopping rule leaves out the rest of the product, which for a slowly decaying inverse power curve is not negligible.

## Decision
Chosen by the owner on 2026-10-24: the inverse power and exponential extensions run to a fixed number of development periods, default 100, exposed as the parameter `extension_periods`, as in the reference package. The stopping rule of 1e-4 is removed from MT14 (version 0.2.0, still a draft): the parameters `stop_below` and `max_extension_years` give way to `extension_periods`, and the failure mode about reaching the limit is replaced by a check of how much the last period still adds. The benchmark criterion is the row `package_100_periods` of each curve. The old values (RAA inverse power 1.0991 against 1.1015; RAA exponential 1.00922; GenIns exponential 1.02934; GenIns inverse power equal at 1.29243) are kept as information in the manifests of `MT14-tail-curves-raa` and `-genins`; the test that compared the two variants checks the information entries.

## Consequences
- P24 builds MT14 with 100 periods by default; the user may change the number.
- The fit still uses factors above 1.00001 as the package does; the spec says "above 1" and no sample factor lies between (0276). Not changed here.
