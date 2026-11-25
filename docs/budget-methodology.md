# Budget Lab methodology

## Historical reference

The default is the most recent contiguous 28-day interval with persisted workspace reporting within the preceding 118 mature calendar days. The shared detection maturity setting defaults to seven full days. The last eligible date is UTC today minus the lag minus one day. If the workspace has no recent 28-day run, choose a mature reference manually. Workspace coverage establishes the default only. Each campaign's expected and observed days are checked independently against its recorded lifetime.

Eligibility requires USD, a purchase objective, positive historical spend and attributed purchase credit, a supported and internally consistent purchase reporting definition, and at least 14 mature reporting days by default. Set `BUDGET_MIN_OBSERVED_DAYS` to change the minimum, from 1 to 28. An expected day missing inside the campaign's lifetime, unusable metrics, inconsistent days, unknown attribution, or a mixed context blocks modeling. Days outside the campaign's lifetime are shown as reduced calendar coverage. An eligible campaign can have fewer observed days than the selected calendar window if it had fewer expected days. Applicable data-quality advisories from current detection results supplement source-integrity checks.

Historical amounts are aggregated from raw persisted spend, purchase credit and attributed value using the Phase 1 KPI service. Historical CPA is spend divided by purchase credit. ROAS is attributed value divided by spend. Average daily spend uses observed reporting days. Missing days stay missing. Observed totals can include partial or blocked campaigns when their underlying measurements are interpretable.

## Normalization and piecewise CPA

For each eligible campaign, multiply its observed spend, attributed credit, and value by `planning days / observed reporting days`. Its normalized spend is `H`. The normalization holds daily rates constant and keeps historical CPA and ROAS unchanged. The proposed campaign budget is `B`.

- Adjust historical CPA by the case's base CPA change, giving `CPA_base`.
- Purchases for spend through `H` equal `min(B, H) / CPA_base`.
- Purchases for spend above `H` equal `max(0, B − H) / (CPA_base × (1 + marginal adjustment))`.
- Modeled attributed value equals modeled purchase credit times historical attributed value per purchase, adjusted by the case's value-per-purchase change.

| Case | Base CPA change | Additional CPA above the historical rate | Attributed value per purchase change |
| --- | ---: | ---: | ---: |
| Conservative | +15% | +30% | −5% |
| Base | 0% | +15% | 0% |
| Optimistic | −5% | +5% | +3% |

These defaults are fictional operating assumptions. All three cases are editable. CPA adjustments range from −90% to +300%, marginal CPA changes from 0% to +300%, and attributed value adjustments from −95% to +300%. Case labels describe assumptions, not confidence bounds. Adjusted cases can be entered in any order, so the labels alone do not establish an ordering of outputs.

Portfolio ratios use sums. Modeled CPA divides total spend by summed purchase credit. Modeled ROAS divides summed attributed value by total spend. Zero denominators yield undefined ratios. Decimal arithmetic preserves fractional purchase credit through calculations. Display uses two decimal places for money and ratios and up to two for credit. Allocations use integer cents or basis points derived from Decimal inputs. The largest-remainder method distributes residual units by fractional entitlement with ascending campaign ID as a stable tiebreaker.

## Comparability and uncertainty

Portfolio conversion metrics are withheld for incompatible definitions. The observed total checks the selected campaigns, the normalized total checks eligible campaigns, and the modeled total checks campaigns receiving spend. Individual outputs remain available for eligible campaigns. Consistent settings across Google Ads and Meta do not deduplicate platform-attributed purchase credit. A dash represents an unavailable or undefined measure.

Extrapolation compares campaign budget with the historical daily rate scaled to planning days. Spend strictly above the normalized historical level through 110% produces a modest warning, above 110% through 150% an elevated warning, and above 150% a substantial warning. A separate warning flags average planned daily spend above the raw peak daily spend. When at least 25% of a campaign or portfolio budget sits above its campaign thresholds, results depend heavily on marginal CPA assumptions. An absolute base CPA adjustment of 25% or more, value adjustment of 20% or more, or marginal CPA increase of 50% or more also draws a warning.

The model applies a simple marginal CPA change across all spend above the historical rate. It does not observe the actual auction response, account for conversion incrementality, or model inventory, audience saturation, changing campaign mix, and seasonality. Its constant normalization assumes the historical daily rate applies throughout the planned period. Use modeled outcomes as sensitivities for planning, alongside separate evidence and controlled experiments.

## Reproducibility

Model version `1.0.0` records the input plan and observation snapshot used to calculate each result. The SHA-256 reference fingerprint covers selected campaign identities and reporting lifetimes, reference dates, and scoped daily aggregates with reporting definitions and source provenance. Uploading unrelated campaign data does not invalidate a saved result. A new calculation may use newer data, model settings, and advisories. Clone reproduces the existing snapshot, while recalculating requires a new save for an alternative. [Budget Lab usage](budget-lab.md)
