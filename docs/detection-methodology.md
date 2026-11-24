# Detection methodology

## Reporting cutoff and evidence

The evaluation date is an exclusive UTC reference. The engine subtracts the configurable maturation lag and one day to determine the last eligible reporting day. The default is seven full days for the workspace's seven-day click window. An evaluation dated November 23 ends on November 15. The configured minimum is seven days. The current and preceding periods each use seven inclusive dates so their weekdays align. An earlier 28-day period provides optional coverage context. The engine uses the same cutoff for every campaign in a run.

With a default manual run, recent data uses the current UTC date. When the latest persisted reporting day is older than the maturation cutoff, the default anchors to that final reporting day and discloses the resulting evaluation date and periods. This supports archived datasets. Send an explicit evaluation date to evaluate calendar gaps after the last upload. The API accepts dates up to the current UTC date.

Campaigns whose recorded lifecycle intersects the current week are eligible. A partial launch or end week yields an incomplete-window suppression. Missing days inside the recorded lifecycle raise a data-quality issue. The status field represents current metadata, so a paused campaign can still have valid historical observations.

Raw observations retain source provenance and attribution context. Two-week rules require compatible measurement in both weeks. D-02 and D-04 require a valid current period. A baseline-only blocker therefore applies to comparisons while the current-period checks can proceed. Known alternate windows and reporting date bases are flagged because their maturation requirements differ from the supported contract. ROAS is attributed value per dollar of spend. Incrementality, profit and customer deduplication require different evidence.

The engine reuses the Phase 1 KPI calculations and sums KPI inputs across each window. Trigger boundaries use Decimal cross-products of the underlying metrics. No comparison relies on averaging daily ratios or on display rounding. Suppression reasons record blocked data, incomplete windows, missing targets, insufficient volume, undefined metrics, and inadequate or unstable scaling history. A valid check that simply misses its trigger is a normal outcome.

## Execution and audit

Select **Run Performance Analysis** in Insights to trigger detection. The action evaluates the bounded reporting window for up to 2,000 campaigns. This operation uses persisted campaign records and works with AI disabled. The development database stores each run, finding, and suppression. Exact repeats return the matching completed run with `reused: true`. PostgreSQL serializes detection with seed and CSV writers to keep the input snapshot consistent.

The completed run with the greatest evaluation date is current, with the highest run ID breaking ties. Backdated runs remain historical. A new accepted observation marks the latest run stale through the append-only performance high-water mark. The stale snapshot remains visible so analysts can inspect the previous basis. A new run refreshes it. CSV import leaves detection execution to the user.

The evaluation manifest is opened by the offline evaluation script only. It contributes no campaign labels to normal detection.

## API

```powershell
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/v1/detection/runs'
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/insights?scope=current&platform=GOOGLE_ADS&page_size=10'
```

Send optional JSON `{"evaluation_date":"2026-11-23"}` to run a specific reporting window. Detection runs and suppressions are paginated. Run history accepts evaluation-date and status filters. The insights list accepts current, historical, or all runs, plus evaluation-date, platform, campaign, policy, severity, and category filters. Suppression audit entries are available at `GET /api/v1/detection/runs/{id}/suppressions`, with their own platform, campaign, and policy filters. A finding links back to its campaign and the evaluated reporting dates.
