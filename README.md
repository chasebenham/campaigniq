# CampaignIQ

CampaignIQ is a marketing performance workspace for **Northstar Outfitters**, a fictional direct-to-consumer outdoor apparel brand. Phase 1 covers standardized Google Ads and Meta Ads imports, purchase-acquisition metrics, and reporting. The fictional business has a $120,000 monthly marketing budget and reports in USD.

The sample portfolio has 16 campaigns and 1,431 observed campaign-days from August 25 through November 22, 2026. The seed and sample CSVs are fictional. Reports identify the presence of seed records, and the product distinguishes platform-attributed purchase credit from customer counts.

## Run locally on Windows

Use Docker Desktop with the Linux container engine running, Python 3.12 or later, and Node.js 22.12 or later. Run the setup from the repository root in PowerShell.

```powershell
Copy-Item .env.example .env
docker compose up -d --wait postgres
py -3 -m venv .venv
& ./.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt
Push-Location backend
& ../.venv/Scripts/python.exe -m alembic upgrade head
& ../.venv/Scripts/python.exe -m app.seed
Pop-Location
Push-Location frontend
npm.cmd ci
Pop-Location
```

If your Python installation exposes `python` on PATH, `python -m venv .venv` is equivalent. The local database binds to `127.0.0.1:5433`. Keep the password and database URL in `.env` in sync if you change them. The example credentials are for loopback development. This phase uses no external AI service.

Start the API in a PowerShell window at the repository root.

```powershell
Set-Location backend
& ../.venv/Scripts/python.exe -m uvicorn app.main:app --reload
```

Start the frontend in a second PowerShell window at the repository root.

```powershell
Set-Location frontend
npm.cmd run dev
```

Open [CampaignIQ](http://localhost:5173) or [API documentation](http://127.0.0.1:8000/docs). Vite proxies `/api` to the API target from `.env`. PostgreSQL stores records in the Compose volume so they persist across service restarts. Stop the database with `docker compose stop postgres`.

## Import a CSV

1. Open **Data Imports** and download the fictional sample or choose a standardized UTF-8 CSV.
2. Select **Preview CSV**. Review the rows that are ready, duplicate, or rejected, including the field-level decisions.
3. Confirm the import. Review its counts and any rejected-row details in history.

The [CSV contract](docs/csv-import.md) specifies the accepted headers, reporting contexts, and duplicate rules. The [fixtures](backend/data/fixtures) include a valid and an invalid fictional example.

## Run tests and build

Set the test database URL to the loopback PostgreSQL service or another disposable test server where the role can create schemas. The integration tests create and drop unique schemas.

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

Omit `CAMPAIGNIQ_TEST_DATABASE_URL` for the fast SQLite and pure-Python tests. The production frontend output is in `frontend/dist`. To serve it locally with the same API proxy, run `npm.cmd run preview` in `frontend` while the API is running. For a separate deployment, route `/api` to FastAPI and return `index.html` for frontend routes.

## Design and methodology

- [Architecture](docs/architecture.md)
- [Data model](docs/data-model.md)
- [Metric definitions and attribution](docs/metrics-methodology.md)
- [CSV import contract](docs/csv-import.md)
- [Synthetic dataset](docs/synthetic-dataset.md)
- [Phase roadmap](docs/phase-roadmap.md)
