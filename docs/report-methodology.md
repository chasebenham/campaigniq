# Strategy Brief measurement and evidence

## Verified performance

The reporting period is inclusive and capped at 90 calendar days. Dates must be complete in UTC. Recent days inside the existing conversion-maturation lag draw a warning. The date range defaults to a current run's evaluated period when available, otherwise to the seven days ending at the most recent mature observation.

The portfolio and separate Google Ads and Meta Ads totals reuse the Phase 1 analytics and KPI services. CPA divides summed spend by total attributed credit. ROAS divides attributed value by spend. The same principle applies to CTR and CPC. Undefined values display as unavailable. Mixed or unknown contexts withhold the affected conversion metrics. Invalid traffic, spend, or conversions are flagged and unusable metrics are withheld. Shared conversions can overlap across platforms. Estimates of causal lift, profit, and unique customers require separate evidence.

Coverage reports the number of calendar dates with data and the number of observed records within expected campaign lifetimes. Missing and out-of-lifetime reports are disclosed. Spend trends group observed daily results into consecutive seven-day intervals, preserving missing dates as gaps. Provenance identifies fictional seed records and uploaded records and includes the latest contributing import date.

## Findings, interpretations, and scenarios

Selected findings retain their policy version, thresholds, stored metrics, date ranges, classification, attribution context, and quality flags. The report presents multiple policies for one campaign as separate observations and warns about overlapping coverage. Financial effects across findings are never added together. Findings with different measurement definitions remain in their respective contexts.

The accepted AI Analyst interpretation must be completed, match its finding, conform to a supported stored schema, and cite actual evidence from its recorded fingerprint. A matching analysis from a historical finding or an analysis grounded in an older evidence snapshot is labeled. Failed or mismatched analyses are excluded. Plausible causes remain hypotheses. A proposed experiment appears only when supplied in an accepted analysis or by management.

The report attaches one saved Budget Lab snapshot. It retains the original assumptions, calculations, attribution context, and warning state. A stale scenario can be deliberately included after acknowledgment. Its historical reference and planning context remain distinct from the report dates. The model compares hypothetical attributed outcomes and cannot establish actual response to higher spend. [Budget Lab methodology](budget-methodology.md)

## Versioning and freshness

Migration `20261124_0007` adds the brief, immutable version, and summary-attempt tables. A save verifies the reviewed evidence fingerprint under the existing source-write lock and atomically adds a version. Revisions must target the current version. Narrative changes are stored separately and preserve the evidence unless the user changes or refreshes it. The snapshot records selected source IDs, stored evidence, provenance, reporting warnings, template version, and the document rendered by both the browser and PDF.

Freshness compares scoped performance and the included finding, analysis, and scenario evidence against their saved fingerprint. The workspace shows if the source evidence has changed. Historical or stale inputs collected after acknowledgment also retain the original warnings. Saved PDF exports preserve the report as it was at save time, including the version and timestamp. Reading a report or exporting it never refreshes its underlying figures.

## Executive synthesis safeguards

The provider receives a bounded catalog of relevant performance, coverage, findings, accepted interpretation excerpts, hypothetical case outcomes, and warnings. Imported names and report strings are treated as data. The provider uses the shared OpenAI Responses API client and structured output constraints. Local checks enforce a schema and unique catalog references, and reject numerical claims and detectable patterns of unsupported causality or significance. Tables present verified quantities independently of the model. Qualitative relevance and business judgment still require a reader's review.

A post-save summary proposal is cached for its version. Pre-save drafting uses a unique request ID for each explicit action and the same audit table and workspace rate limit. The provider uses a 25-second timeout per attempt and the configured retry bound. Output caps are 1,400 tokens for post-save synthesis, 2,000 for an inline field, and 5,000 for all five. The database transaction closes before the provider call. Results are checked again against the version and evidence. The attempt records its outcome, provider usage when available, model, prompt version, schema version, and evidence fingerprint.

Inline drafting sends only the selected evidence and section instructions. Structured references must exist in the catalog. Numeric markers are checked against the source's exact or display-rounded value and unit, then rendered from the verified number. Unbound figures, invalid citations, and detectable unsupported claims cause rejection. Budget figures require explicit hypothetical context. A proposal based mainly on blocked measurement must prioritize validation. These checks cannot establish that every qualitative explanation is well supported or that a proposed experiment is feasible.

Revision `20261124_0008` allows audit records before a report version exists. Saving stores per-field metadata in the existing immutable version JSON. Source changes preserve text and flag earlier evidence. A late result requires review and cannot automatically replace editor text after edits or selection changes.
