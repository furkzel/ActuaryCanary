# 0059 — Diagnostics beside the methods and in the terminal summary

## Context
P08 returns diagnostics as data (0039). The owner asked for plain tables beside each method result and a one-line count per line of business in the terminal summary; the executive report is a later item.

## Decision
- The report shows, per segment and line, after the existing tables: ultimates by method with the selected one and why, the Mack standard error with the lognormal range of the selected reserve (labelled an approximation), the inflation-adjusted chain ladder, a diagnostics table (triangle, method, diagnostic, where, what), and the factor stability tables in a collapsible block. A method that did not run is listed with its reason. The summary table gains the selected ultimate and IBNR. The methods section names the new methods, and the assumptions in force are a collapsible table.
- Thin evidence is raised once per group and names the methods that ran, not once per method and triangle, so the count per line is not inflated. The diagnostics counted are the five of P08: thin evidence, late development with tail 1.0, a factor on fewer than three origins, a zero-denominator cell, a paid ultimate below the incurred to date. Methods that did not run are not diagnostics; they are in the module reasons.
- The terminal gets one line, wrapped at 78 columns, "Method diagnostics: n (LINE n, ...)". The tables are not widened.
- The thin-evidence threshold stays at P08's 8 origin periods (0039). The brief of this item says "fewer than four"; the code was not changed, because the brief also forbids changing thresholds. With 4 origin periods the tiny baseline shows the warning; with a threshold of 4 it would not.

## Consequences
- The report page grows by about five tables per group; the executive report decides what stays.
