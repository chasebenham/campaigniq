# AI Analyst

AI Analyst interprets a saved deterministic finding. It presents hypotheses, a proposed manual next step and, where appropriate, an experiment. The verified measures and cited evidence values come from CampaignIQ. The interpretation comes from the configured model.

## Enable locally

Start from the [local setup](../README.md). Install the updated Python requirements, apply the latest migration, and set these variables in the repository-root `.env`.

```dotenv
AI_ANALYSIS_ENABLED=true
OPENAI_API_KEY=
OPENAI_MODEL=gpt-6-luna
AI_REQUEST_LIMIT_PER_HOUR=8
AI_PROVIDER_MAX_ATTEMPTS=2
```

Supply your project key in the repository-root `.env`. CampaignIQ defaults to `gpt-6-luna` when `OPENAI_MODEL` is blank. An explicit environment value selects that model. Process environment variables take precedence over the file. Use a model available to your project that supports the Responses API and strict Structured Outputs. The example defaults to disabled with a blank key. [Model catalog](https://developers.openai.com/api/docs/models)

After changing `.env`, stop the backend with Ctrl+C and start it again from the repository root. Refresh the AI Analyst page. **Check OpenAI connection** runs a model metadata lookup and caches the result for one minute. It sends no campaign evidence and generates no text. The status API distinguishes disabled, missing-key, configured, accessible, and provider-error states. Opening or refreshing the page only reads local state and saved history.

```powershell
Set-Location backend
& ../.venv/Scripts/python.exe -m uvicorn app.main:app --reload
```

Open **Insights**, run performance analysis, and open a finding. Select **Review in AI Analyst**, inspect the evidence, then select **Analyze with AI**. Opening the workspace, running detection, and importing CSVs leave the provider idle. Each finding's history is available when the provider is disabled.

## Evidence and validation

The backend stores a canonical snapshot of the selected finding before it sends a request. It includes campaign name, platform and objective, policy, severity, mature dates, verified metrics and comparison periods, targets, thresholds, reporting definitions, attribution limits and relevant quality flags. Campaign names and imported text are data. The model receives neither tool definitions nor advertising connectors. The provider request uses the official Python SDK, the Responses API and a Pydantic Structured Outputs contract with `store=False`. [Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs)

The provider receives a strict JSON Schema scoped to the finding ID and its allowed reference paths. The server validates the returned shape, exact reference paths, and supporting evidence again. CPA deterioration cites CPC and purchase CVR in both periods when available. Scaling cites current and target ROAS and requires a controlled experiment. Data-quality findings require a flag or coverage citation and prioritize investigation or monitoring. Evidence reference values are rendered from the saved snapshot. Narrative fields use qualitative directions and citations for numbers. Proposed experiment parameters can contain quantities. The report separates diagnostic hypotheses, missing information, the manual action and its rationale, and the experiment's comparator, measures and stopping criteria.

The validated output is saved alongside the model identifier, prompt and schema versions, evidence fingerprint, timestamps, status and any returned token counts. Structural validation can check grounding paths and some numerical claims. Assessing causal wording, sufficiency of citations and experiment quality still requires human review.

## Controls and failure recovery

- Explicit requests use `POST /api/v1/insights/{finding_id}/analyses`. The backend assembles all evidence. The button requires current evidence.
- Each new request uses a server-wide rolling hourly allowance, eight by default. Rate-limit responses include `Retry-After`. Each provider attempt has a 25-second request timeout, with at most one transient retry. Set `AI_PROVIDER_MAX_ATTEMPTS=1` for manually bounded smoke tests. The output budget is 2,800 tokens per attempt. Failed validations may still incur provider charges. Returned usage includes cache details when available. [OpenAI pricing](https://developers.openai.com/api/docs/pricing)
- A matching pending attempt returns HTTP 202. A normal request reuses the latest matching completed attempt with HTTP 200. The identity includes the finding, evidence fingerprint, model, prompt and schema versions. **Regenerate analysis** sends the latest completed ID and an idempotency UUID. Successful regeneration becomes the current analysis and preserves earlier versions. Duplicate clicks or competing requests against the same prior version reuse the resulting attempt. The reservation expires after 90 seconds if a worker stops before completion.
- The reservation transaction ends before the provider call. A separate short transaction verifies whether the original finding and evidence are still current. Output generated during a concurrent data or run change is stored as stale. Earlier analyses remain readable with their original references.
- Invalid output and provider failures create a history entry. Server responses expose controlled validation reasons and sanitized provider errors. If validation fails, the history retains any token usage and discards the unvalidated prose.

| Status | What to check |
| --- | --- |
| Disabled | Set `AI_ANALYSIS_ENABLED=true` in the root `.env` and restart FastAPI. Check for an overriding process setting. |
| Missing credentials or rejected key | Verify the server key and project. Reload the backend, then check the connection. |
| Model unavailable or permission denied | Check the model identifier and project/key permissions. Model lookup and generation permissions can differ. |
| Quota, rate limit or timeout | Check billing and request limits. Retries for temporary failures are bounded. |
| Invalid output | Inspect the reason in analysis history. Retry explicitly if your call budget permits. |

```powershell
$ciqApi = 'http://127.0.0.1:8000/api/v1'
Invoke-RestMethod "$ciqApi/ai/status"
Invoke-RestMethod -Method Post "$ciqApi/ai/status/check"
$ciqFinding = (Invoke-RestMethod "$ciqApi/insights?scope=current&page_size=1").items | Select-Object -First 1
# The next command requests a provider call if no matching saved analysis exists.
Invoke-RestMethod -Method Post "$ciqApi/insights/$($ciqFinding.id)/analyses"
Invoke-RestMethod "$ciqApi/insights/$($ciqFinding.id)/analyses"
```

CampaignIQ Phase 2 targets a trusted local operator. Shared installations require authentication, authorization, and an approved policy for transmitting campaign evidence.
