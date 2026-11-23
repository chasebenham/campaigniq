# CSV import contract

Use a standardized UTF-8, comma-delimited CSV for Google Ads or Meta Ads. Native export files require a mapping to the CampaignIQ schema before upload. The application accepts up to 5 MiB and 20,000 nonblank data records per file. Header order is flexible. Headers are case-insensitive, and extra named columns are ignored. Standard CSV quoting and an optional UTF-8 byte-order mark are supported.

| Required column | Expected value |
| --- | --- |
| `date` | ISO calendar date `YYYY-MM-DD` |
| `platform` | `GOOGLE_ADS` or `META_ADS` |
| `campaign_id` | Platform-scoped text ID, up to 100 characters. Leading zeros are preserved |
| `campaign_name` | Nonempty text, up to 180 characters |
| `impressions`, `clicks` | Nonnegative whole counts, with clicks at most impressions |
| `spend` | Nonnegative USD decimal with up to 4 decimal places |
| `attributed_purchases` | Nonnegative decimal with up to 6 decimal places. Zero is valid |
| `attributed_purchase_value` | Nonnegative USD decimal with up to 4 decimal places |
| `conversion_action` | `PURCHASE` |
| `attribution_method` | `LAST_CLICK`, `DATA_DRIVEN`, or `LINEAR`. Fractional purchase credit is accepted for data-driven or linear |
| `attribution_window` | `7D_CLICK` |
| `date_basis` | `INTERACTION_DATE` |
| `currency` | `USD` |

Use plain decimal notation without currency symbols, thousands separators, or exponents. The importer trims whitespace. Case is normalized for platform, currency and attribution tokens. Mark unavailable reporting metadata explicitly as `UNKNOWN`. Preview recognizes this token for attribution fields and rejects those rows because the workspace requires an identified reporting context. Recognized noncanonical click or view windows and conversion-date reporting also produce row-level incompatibility errors.

## Preview and commit

Preview parses the file, classifies all rows, and returns counts, up to 25 parsed rows, up to 100 row-level issues, and a review token. A malformed file or missing required header produces a file-level error. Preview performs no writes. On commit, the API takes a PostgreSQL transaction lock shared with the seed command and checks the same file again. Changes in the bytes or in the validation outcome produce HTTP 409 and a prompt to preview again. Ready rows, new campaign metadata, the import audit, and rejected-row issues are committed together.

The following rules apply to candidate observations, after field-level and context validation.

- A row matching the stored campaign-day's raw metrics and context is counted as a duplicate and skipped.
- A row with different metrics or context for an existing campaign-day is rejected. The stored record takes precedence.
- For an unused campaign-day with several identical candidate rows, the first is ready and the rest are duplicates. If candidates disagree, all conflicting rows are rejected.
- The first importable reporting method establishes a campaign's context. An existing campaign's stored method takes precedence. New campaigns with multiple competing methods in one file are rejected until the source is corrected.
- The campaign name is metadata. Renaming the campaign in an export leaves the existing name intact and does not affect performance duplicate matching.

A confirmed file can be `COMPLETED`, `COMPLETED_WITH_ERRORS`, `REJECTED`, or `NO_NEW_ROWS`. The final two states allow retaining the audit even when there are zero ready rows. History paginates the committed audit records and their validation issues.

## API example in PowerShell

From the repository root, preview the fictional example and send the same file with the resulting token.

```powershell
$ciqSample = 'backend/data/fixtures/valid.csv'
$ciqPreview = curl.exe --fail-with-body -sS -F "file=@$ciqSample" http://127.0.0.1:8000/api/v1/imports/preview | ConvertFrom-Json
$ciqPreview | ConvertTo-Json -Depth 6
curl.exe --fail-with-body -sS -F "file=@$ciqSample" -F "preview_token=$($ciqPreview.token)" http://127.0.0.1:8000/api/v1/imports/commit
```

Use `backend/data/fixtures/invalid.csv` to inspect validation for negative spend, incompatible attribution, missing identifiers, bad numerics, and unsupported currency. Both fixtures contain fictional data.
