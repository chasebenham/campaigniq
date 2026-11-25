# Strategy Brief verification

## Run the checks

Run from the repository root in PowerShell.

```powershell
docker compose up -d --wait postgres
& ./.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt
$env:CAMPAIGNIQ_TEST_DATABASE_URL = 'postgresql+psycopg://campaigniq:campaigniq_dev@127.0.0.1:5433/campaigniq'
Push-Location backend
& ../.venv/Scripts/python.exe -m alembic upgrade head
& ../.venv/Scripts/python.exe -m pytest -q
Pop-Location
Push-Location frontend
npm.cmd test
npm.cmd run build
Pop-Location
```

The database suite uses disposable PostgreSQL schemas. Independent financial fixtures check portfolio weighting, incompatible attribution, partial coverage, and PDF values. Tests also cover finding eligibility and deduplication, accepted AI result selection, budget inclusion and staleness, changed-source conflicts, immutable revisions, caching and concurrent synthesis, missing configuration, provider errors, and historical PDF exports.

AI tests inject provider responses. They verify structured parsing, evidence references, unsupported numerical claims, timeout recovery, version races, token metadata, and manual application of a generated proposal. The normal test suite makes no OpenAI calls.

## Browser verification

Chrome used a production build and a disposable copy of the local fictional PostgreSQL workspace. The browser created a fictional Budget Lab scenario and a strategy brief for November 3–16, 2026. It included New Customer Acquisition’s CPA finding and existing accepted analysis, Alpine Collection Video’s reporting issue, and the All-Weather Gear Shopping scaling finding. It previewed and saved the report, reloaded with unchanged values, exported version 1, revised commentary, and reopened the previous version. Saved data also reopened after a QA backend restart.

Browser checks followed contextual links from Insights, AI Analyst, and Budget Lab, verified a 390-pixel viewport, and saved a second report with performance evidence only. The browser ran with AI generation disabled throughout and reused the existing analysis. Optional synthesis was verified with mocked responses, with no additional paid provider calls. [PDF visual verification](pdf-export.md)

## Results

- Backend with PostgreSQL enabled passed 105 tests. Alembic detected no schema drift.
- Frontend passed 20 tests and the Vite production build succeeded.
- All five sample PDF pages passed visual inspection. The sample contained only fictional seed performance records.
- Applying revision `20261124_0007` to the existing local workspace preserved its 1,433 performance records and three accepted AI analyses. Overview, Campaigns, Data Imports, Insights, AI Analyst history, Budget Lab, and Strategy Briefs responded after the migration.
- No new live OpenAI requests were made for executive synthesis. Provider behavior for this action was tested with mocks.

## Inline AI commentary drafting

The enhancement passed 118 backend tests with isolated PostgreSQL and 24 frontend tests. The production build succeeded. Mocked coverage includes all five single-field actions, the batch action, request replay, rounded values, invalid references and units, provider errors, source drift, management edits, the legacy post-save proposal, and report/PDF persistence.

Two live GPT-6 Luna requests ran against the fictional workspace on November 24, 2026 with retries disabled. Both passed validation.

| Action | Input tokens | Output tokens | Estimated USD |
| --- | ---: | ---: | ---: |
| Executive summary | 7,121 | 340 | $0.00106005 |
| Draft All Five | 8,520 | 1,206 | $0.00166793 |

The estimates use Standard short-context rates and the reported 7,118 and 8,517 cache-write tokens, respectively, with zero cache reads. The live drafts omitted inline quantities. Automated tests cover numeric validation and legitimate display rounding. Spot review confirmed the acquisition-cost deterioration and the blocked baseline, and the draft experiment proposed a retained comparison, attributed ROAS, guardrails, and an attribution-maturity check. Review is limited to the two outputs and does not establish experiment feasibility or results. [GPT-6 Luna pricing](https://developers.openai.com/api/docs/models/gpt-6-luna)

Chrome verified overwrite cancellation, batch generation, manual editing, preview, save, reload, and PDF download. All eight pages of the final fictional export were rendered and visually inspected, including distinct AI and management-edited labels. Migration `20261124_0008` applied without schema drift and preserved existing records.
