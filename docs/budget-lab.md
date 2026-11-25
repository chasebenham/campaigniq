# Budget Lab

Budget Lab lets Northstar Outfitters compare hypothetical, human-directed paid-media allocations using persisted Google Ads and Meta Ads campaign history. Model outputs depend on specified assumptions. Estimating incremental revenue, deduplicated customer acquisition, profit, and real auction response requires other evidence.

## Plan an allocation

1. Open **Budget Lab** from the workspace navigation. CPA deterioration and scaling findings in Insights and AI Analyst can open a draft with the finding's campaign selected. The link carries its finding ID and starts without an allocation.
2. Review the reference dates and select at least two eligible campaigns. Open a campaign's benchmark details to see its reporting definitions, missing dates, and any blockers. Blocked campaigns can remain in the historical comparison with a zero allocation.
3. Set the future dates and total USD budget. Choose dollar or percentage inputs. Use **Restore historical allocation** to split the proposed budget by normalized historical spend among eligible campaigns, or use **Equal allocation**.
4. Edit individual entries. Other amounts stay fixed. The balance control assigns the exact remaining amount to the last selected eligible campaign. It can also subtract an overage when that campaign has enough allocated. Balance a populated draft before switching units. Conversion to two-decimal percentages can slightly change the cent split when converting back.
5. Use **Assumption case** to edit each of the three cases. Select **Calculate scenarios** after balancing and review the historical observations, normalized baseline, campaign projections, and extrapolation warnings.
6. Select **Save scenario**. Find it in **Saved scenarios** and open it after reloading or restarting. **Clone scenario** copies the recorded snapshot and retains a source link. **Use as draft** copies its inputs for editing, recalculation, and saving as a separate scenario. **Compare with** places the three case results for two saved scenarios side by side. When plans use different dates or evidence, compare cautiously.

Budget Lab makes no calls to OpenAI or advertising platforms. Strategies and assumptions remain under the user's control.

## Controls and persistence

Inputs support up to 20 selected campaigns, inclusive reference and planning ranges of 1–90 calendar days, and a USD budget from zero to $100 million. Planning starts today or later in UTC and follows the reference period. Percentage entries sum to exactly 100.00% and dollar entries sum to the budget. Currency and percentage inputs allow two decimal places.

Saved scenarios contain plan dates, allocations, all three assumption sets, selected campaign links, optional finding context, model version, evidence fingerprint, and timestamps. The calculation snapshot stores reference evidence, normalized baselines, modeled outcomes, and warnings. PostgreSQL holds separate tables for the scenario, campaign membership, and one-to-one calculation result. Changed reference inputs mark an existing snapshot stale. Viewing or cloning it preserves the original values and calculation timestamp. A new save uses a server-side calculation and refuses a reference fingerprint that no longer matches the reviewed evidence.

## API

All paths use `/api/v1/budget-lab`. OpenAPI documents the request and response schemas.

| Method and path | Behavior |
| --- | --- |
| `GET /assumptions` | Default assumptions, available reference dates, maturity cutoff, minimum observation length, and planning defaults |
| `GET /eligible-campaigns` | Paged campaign benchmarks, including blocked campaigns, filterable by date pair, platform, campaign ID, and name |
| `POST /allocations` | Historical or equal split, or conversion of an already balanced allocation |
| `POST /calculate` | Deterministic calculation and evidence fingerprint for the submitted plan |
| `GET /scenarios` | Paged saved scenarios and their current source status |
| `POST /scenarios` | Recalculate and persist the submitted plan against the reviewed evidence fingerprint |
| `GET /scenarios/{id}` | Read the saved input and output snapshot |
| `POST /scenarios/{id}/clone` | Copy a snapshot under a new ID with optional name |

Apply Alembic revision `20261124_0006` before opening the workspace. [Local setup](../README.md) · [Modeling methodology](budget-methodology.md) · [Verification](budget-scenario-tests.md)
