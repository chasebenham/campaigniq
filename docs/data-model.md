# Data model

## Campaign

`campaigns` owns the internal integer ID used in API routes. The pair of `platform` and `external_campaign_id` is unique. A Google campaign and a Meta campaign can have the same external ID. Supported platforms are `GOOGLE_ADS` and `META_ADS`. The objective is `PURCHASES`. Status is `ACTIVE`, `PAUSED`, or `COMPLETED`. Currency is USD. Target CPA and ROAS are optional positive fixed-point decimals. Campaigns track a start date, optional end date, and creation and update timestamps.

CSV can create campaign metadata with the supplied name, an active status, and the first observed report date. An accepted earlier observation moves that start date earlier. Importing additional data preserves the stored campaign name, status and targets. Dates after a campaign's recorded end are rejected.

## Daily campaign performance

`daily_campaign_performance` stores at most one observation for each internal campaign ID and report date. The measurement grain and unique key apply across imports. The table stores impressions and clicks as BIGINT, spend and attributed purchase value as NUMERIC(18, 4), and attributed purchases as NUMERIC(18, 6). Each observation explicitly stores the conversion action, attribution method, window, date basis, originating import ID, and creation timestamp.

The CSV service requires one attribution method per campaign and the shared purchase, click-window and interaction-date contract. Campaigns with a different supported attribution method can coexist. Report calculations apply context checks before publishing conversion totals. An index beginning with report date supports reporting ranges. The import foreign key has its own index for source lookups.

## Import audit

`data_imports` records the filename, optional source platform, import time, total/added/rejected/duplicate row counts, terminal status, validation summary, and source type. A missing platform means the source was mixed or unspecified. Totals reconcile to added + rejected + duplicate. Source type is `SYNTHETIC_SEED` or `CSV_UPLOAD`. Analytics uses the source type to flag fictional seed rows.

`import_validation_errors` stores the original one-based CSV line number, optional field name, error code, and user-facing message. Several issues may point to a single rejected row. Its indexed import/line ordering supports pagination. Performance foreign keys restrict deletion of referenced campaign and import records.

Alembic revision `20261123_0001` creates the four tables, constraints, and indexes. PostgreSQL tests verify both migration directions in isolated schemas.
