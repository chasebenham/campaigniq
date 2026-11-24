# Fictional detection evaluation

This offline score compares policy version 1.0.0 with the original Phase 1 scenario manifest. It uses persisted fictional seed observations and the default policy thresholds. The normal application reads campaign records and reporting definitions alone.

## Reproduce

Apply migrations and load the seed into a local evaluation database. Run from the repository root in PowerShell.

```powershell
Push-Location backend
& ../.venv/Scripts/python.exe -m evaluation.detection
Pop-Location
```

Use `--output path.json` for campaign-level matches, unmatched detections, missed expectations, cutoffs, and suppression counts.

## Matching

The evaluation uses 12 reporting cutoffs. It starts on September 7, 2026, advances by seven days, and adds the November 22 dataset endpoint. Every cutoff still applies two complete seven-day windows and the nominal maturation rule. Historical cutoffs simulate an as-of date after the configured lag.

Each planted campaign maps to its primary policy. Declining efficiency maps to D-01, inefficient spend to D-02, conversion decline to D-03, potential scaling to D-05, and coverage gaps to D-06. A pair matches if it triggers with a current-period end inside the planted interval. For D-06, a missing-date flag must contain a date inside the planted gap. Repeated findings count once per campaign and policy. A pair detected only outside its labeled window contributes an unmatched detection and a missed expectation. Precision and recall are undefined when their denominator is zero.

## Measured results

| Policy | True positives | False positives | False negatives | Precision | Recall |
| --- | ---: | ---: | ---: | ---: | ---: |
| D-01 CPA deterioration | 3 | 9 | 0 | 25.00% | 100.00% |
| D-02 ROAS below target | 2 | 6 | 0 | 25.00% | 100.00% |
| D-03 CVR decline | 1 | 11 | 1 | 8.33% | 50.00% |
| D-04 Spend without purchases | 0 | 0 | 0 | — | — |
| D-05 Potential scaling | 2 | 11 | 0 | 15.38% | 100.00% |
| D-06 Data quality | 2 | 0 | 0 | 100.00% | 100.00% |
| **Overall** | **10** | **37** | **1** | **21.28%** | **90.91%** |

The single miss was Hiking Essentials Promotion, NS-G04. The October 19 cutoff included only the first day of the planted decline and showed a CVR change of −10.90%. On October 26 CVR fell 20.05% while CTR rose 11.13%, outside the ±10% gate. The November 9 CVR decline of 14.23% fell short of the 15% trigger. The campaign had sufficient purchases in each comparison. The timing of the step change, week-to-week variation, and CTR guard explain the miss.

The workload produced 87 suppressions. Low volume accounted for 48, covering 12 windows for each of D-01, D-02, D-03 and D-05 on the low-volume campaign. Data quality accounted for 16 campaign-window-policy suppressions. Scaling instability accounted for 22 and the CTR gate accounted for one.

The manifest labels one primary pattern per campaign. An unmatched D-02 or D-05 can still meet the policy because its target is crossed. A conversion decline can also raise CPA. Stable cohorts still vary week to week, so some threshold crossings indicate noisy alerts. Treat 21.28% as agreement with these sparse fictional labels. A real-world precision estimate requires independently adjudicated windows and a representative sample. The manifest has no labeled D-04 positives, so D-04 behavior is verified with explicit zero-credit fixtures. The seed, labels and configured thresholds were preserved.

## Phase 2A verification

The milestone passed 47 backend tests, including six isolated PostgreSQL integration tests, eight frontend tests, and the frontend production build. PostgreSQL revision `20261123_0002` was applied to the local database.
