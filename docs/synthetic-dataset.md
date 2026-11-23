# Fictional synthetic dataset

Northstar Outfitters is a fictional direct-to-consumer outdoor apparel company with a nominal $120,000 monthly marketing budget. The deterministic seed represents 8 Google Ads and 8 Meta Ads campaigns from August 25 through November 22, 2026, inclusive. The 90-day portfolio contains 1,431 observations out of 1,440 possible campaign-days.

The generator uses the fixed seed `18273`, platform-specific impressions and click rates, campaign-specific cost and conversion distributions, and weekday differences. Impressions determine clicks, clicks and CPC determine spend, purchases are drawn from clicks and conversion probability, and order values are drawn per purchase. Spend is scaled to the order of magnitude of the stated budget. Budget is business context, and daily delivery varies by campaign and date.

The data uses USD and a fictional standardized reporting definition of purchase, last click, a seven-day click window, and interaction date on both platforms. Data-quality scenarios omit nine observations. The malformed records are separate fictional validation fixtures.

From the repository root, run:

```powershell
Push-Location backend
& ../.venv/Scripts/python.exe -m app.seed
Pop-Location
```

The seed adds missing campaign-days where the reporting context and campaign dates permit them. It preserves existing campaign metadata and campaign-days, including uploaded records. A second run against a fully seeded database adds zero rows. Seed provenance is persisted as `SYNTHETIC_SEED`.

The [scenario manifest](../backend/data/scenario-manifest.json) documents the exact fictional cohorts and evaluation periods. It is reserved for Phase 2 offline evaluation. The KPI engine, analytics endpoints and UI operate on measured values and stored reporting metadata.
