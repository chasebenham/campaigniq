# CampaignIQ roadmap

## Phase 1 · Data and performance analytics

Phase 1 covers the PostgreSQL reporting model, deterministic fictional seed, CSV validation and audit trail, Decimal KPI calculations, and three reporting and import workspaces.

## Phase 2 · Performance and data-quality detection

1. Specify the detection unit, lookback and comparison windows, denominator requirements, and measurement-context rules before tuning detectors.
2. Build deterministic baselines for changes in CPA, ROAS, CVR and spend. Use weekday-matched comparisons and guard against low volume and incomplete coverage.
3. Evaluate detections against the held-out scenario manifest by campaign and time window. Measure precision, recall, false positives on stable campaigns, and time to first valid detection.
4. Store detection evidence, thresholds, affected periods, and raw numerators and denominators so analysts can reproduce each finding.
5. Surface results in the Insights workspace with attribution caveats and the related campaign view.

AI-assisted analysis, budget modeling, and executive reports are later phases.
