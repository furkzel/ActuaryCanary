# 0072 — One visual system for the report

## Context
Blueprint 11: the same colour always means the same segment or basis, ranges are drawn as ranges, one message per chart, readable when printed.

## Decision
- Colour names a basis or a segment and nothing else. Paid is blue and incurred orange everywhere, heatmaps included, each on its own one-hue ramp. Segments: NON_LIFE violet, LIFE aqua, PENSION yellow, HEALTH magenta (the fourth has no phase 1 data). The selected ultimate is drawn in ink. Methods on one triangle share the basis colour and differ by marker shape, with a legend. The segment trio passes the colour-vision checks for all pairs in light and dark, and paid and incurred pass as a pair. Bars by line carry the line name on the axis, so identity never rests on colour alone.
- Colours are CSS tokens; figures name tokens and the page resolves them when drawing, so light, dark and print use one figure specification. Printing forces the light theme and opens collapsed blocks.
- The reserve range is drawn as central ranges around the selected reserve: 25th to 75th percentile dark, 5th to 95th light, the selected reserve (the lognormal mean) as a diamond. A bar from the 75th to the 99.5th percentile of RS03 left the mean outside the bar on baseline medium, which reads wrongly; those upper percentiles stay in the table.
- One message per chart: written premium by line; incurred to date by line; ultimate loss ratio by origin, one small chart per line; share flagged by line with MT08's limit dashed; one heatmap per triangle; link ratios with the selected factor per triangle; ultimates by method; the range.

## Consequences
- Figures are small JSON; plotly is embedded once, and the page is about 5.0 MB on the tiny and the medium baseline.
