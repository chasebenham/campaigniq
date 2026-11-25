# Budget Lab verification

## Calculation fixtures

The independent backend fixture has two complete campaigns with daily spend of $10 and $20, one attributed purchase per day each, and attributed value of $20 and $40 per day. Their 14-day observed portfolio has $420 spend and 28 attributed purchases. Over a 28-day planning period, normalization yields $840 spend, 56 attributed purchases, $1,680 attributed value, $15 CPA and 2.00× ROAS.

With $280 allocated to the first campaign and $583 to the second, $23 sits above the second campaign's normalized $560 spend. Under Base, the second campaign's marginal CPA is $23. The expected complete plan has $863 spend, 57 modeled attributed purchases, $1,720 modeled attributed value, CPA of $863 / 57, and ROAS of $1,720 / $863. Separate expected values verify Conservative and Optimistic outcomes. Coverage also includes the exact historical breakpoint, extrapolation boundaries, cent reconciliation, zero budgets, invalid totals, and undefined ratios.

The API suite checks maturity, gaps, low coverage, zero credit, unknown or mixed attribution, blocked allocation, sorting and filtering, and pagination. Compatibility tests check that cross-context portfolio conversions are withheld while eligible individual models remain available. PostgreSQL tests apply the migration to a disposable schema, save and reopen from a new connection, import a missing historical observation, verify stale status and identical frozen values, and verify clone lineage.

## Run the tests

From the repository root in PowerShell with the local PostgreSQL service running:

```powershell
$env:CAMPAIGNIQ_TEST_DATABASE_URL = 'postgresql+psycopg://campaigniq:campaigniq_dev@127.0.0.1:5433/campaigniq'
Push-Location backend
& ../.venv/Scripts/python.exe -m pytest -q
Pop-Location
Push-Location frontend
npm.cmd test
npm.cmd run build
Pop-Location
```

The Vitest workflow exercises campaign selection, exact remaining budget feedback, historical reset, invalid input, assumption editing, case switching, warning rendering, save and reopen, and opening Budget Lab from a verified finding.

## Browser verification

A production build was served through the Vite proxy with a separate FastAPI process and a disposable PostgreSQL database. Headless Chrome selected two eligible fictional campaigns and Alpine Collection Video. The browser confirmed the latter's reporting gap and blocked allocation. The test restored historical proportions, switched to percentage inputs, balanced a $180,000 budget to 55% and 45%, and set Optimistic CPA change to −7.5%. It reviewed all case outputs and extrapolation warnings, saved the scenario, reloaded it, and confirmed the saved inputs and result matched. It also cloned and compared the snapshots, reopened the clone as an editable draft, and checked the 390-pixel layout for page overflow.

After restarting the QA API, Chrome reopened the saved scenario with the same results and assumptions. The Insights and AI Analyst links each selected the campaign from a persisted scaling finding. The planning workflow generated API posts only to Budget Lab, and reopening snapshots or following the context links generated no posts.

The full backend suite passed 94 tests with PostgreSQL enabled. All 16 frontend tests passed and Vite built the production bundle. On the local development database, revision `20261124_0006` applied with all 1,433 performance records and the three accepted analyses still present.

This verifies software behavior on fictional data. Scenario values remain hypothetical and do not establish forecast accuracy.
