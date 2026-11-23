# Metrics methodology

All ratios use sums of raw measures for the current filter set. For example, period CPA uses total period spend divided by total attributed purchases. Averages of campaign or daily ratios can yield materially different values.

| Metric | Formula | Unit |
| --- | --- | --- |
| CTR | Clicks ÷ impressions × 100 | Percent |
| CPC | Spend ÷ clicks | USD |
| CPM | Spend ÷ impressions × 1,000 | USD |
| Purchase CVR | Attributed purchases ÷ clicks × 100 | Percent |
| CPA | Spend ÷ attributed purchases | USD |
| ROAS | Attributed purchase value ÷ spend | Multiple |
| Attributed AOV | Attributed purchase value ÷ attributed purchases | USD |

PostgreSQL stores traffic as integers and money and attribution credit as fixed-point NUMERIC. The backend uses Decimal arithmetic with a 40-digit context for sums and division. The API sends decimal results as strings. The UI displays money, rates and multiples to two places, impressions and clicks as whole counts, and attributed purchase credit to six places when precision is present.

A zero denominator yields null and displays as an em dash. A zero numerator with a positive denominator yields zero. For a day with spend, clicks and zero purchases, CVR and ROAS can be zero, while CPA and attributed AOV are undefined. A selection without observations has null metrics and an empty state. A missing campaign-day denotes absent reporting. The campaign trend displays a gap, and campaign detail counts missing days between the selected bounds or, where a bound is omitted, the first or last observation.

## Attribution and comparability

A reporting definition comprises the conversion action, attribution method, attribution window, and date basis. Phase 1 imports purchase data with a 7-day click window and interaction-date reporting. Campaigns may use last-click, data-driven, or linear credit, with a consistent method per campaign. The fictional seed assumes the same last-click context across both platforms.

When a selection contains incompatible or unknown conversion definitions, aggregate conversion credit, value, CVR, CPA, ROAS, and AOV are unavailable. The same safeguard applies to the whole daily series for that selection. Traffic and spend remain available under the reporting contract. Platform and campaign reports each evaluate the context of their own records and display the reporting definitions.

Cross-platform sums represent platform-attributed purchase credit and value. A purchase may receive credit on both platforms, and fractional credit may represent part of one attributed purchase. Use these totals for platform reporting and treat deduplicated customers, incremental revenue, and profit as separate measures. ROAS describes attributed purchase value per dollar of ad spend. Spend and attribution may also differ by platform reporting timezone and revision practices. Align exports to consistent reporting dates before uploading.
