# AI Analyst evaluation

The reproducible offline cases cover the six policies and one insufficient-evidence outcome. They construct fictional campaign weeks and run the production deterministic evaluator. For each eligible finding they check independently specified expected raw or derived values, then validate a hand-authored representative response against its evidence snapshot. The insufficient-evidence case verifies that a suppression does not create an analysis target.

```powershell
Push-Location backend
& ../.venv/Scripts/python.exe -m evaluation.ai
Pop-Location
```

| Case | Expected evidence and review focus |
| --- | --- |
| CPA deterioration | Ground current and baseline CPA and explain possible budget pressure. Treat delivery mix as a hypothesis. |
| ROAS below target | Cite actual and target ROAS. Investigate attributed order value without assuming profit or incremental sales. |
| Purchase CVR decline | Cite the CVR and stable CTR evidence. A proposed controlled test needs a comparator and a primary outcome. |
| Spend with zero purchase credit | Distinguish a reported zero from missing tracking data. Prioritize measurement reconciliation. |
| Potential scaling | Cite the target gap and stability evidence. Use a bounded test with a spend cap and a marginal performance measure. |
| Reporting gap | Cite expected coverage or the flagged days. Prioritize measurement repair and rerun detection. |
| Insufficient evidence | The volume gate suppresses escalation. An analyst can inspect the suppression without generating an AI interpretation. |

## Human review rubric

For a candidate model's saved responses, review each eligible case using the original evidence snapshot. Record pass, fail or unclear for each criterion and quote the relevant claim if it needs review.

1. **Numerical fidelity**. Cited values, dates, campaign and direction match the saved evidence.
2. **Grounding**. References support the main observation and material claims.
3. **Limitations**. The response distinguishes attribution from incrementality and identifies material data gaps.
4. **Action fit**. The next step is concrete, manual, and proportionate to evidence quality.
5. **Experiment specificity**. When proposed, the experiment defines a control or comparator, scope, duration, guardrails, an outcome and a decision rule.
6. **Causal discipline**. Possible explanations are labeled as hypotheses. The response avoids invented inspections, results, significance, or causal certainty.
7. **Marketing reasoning**. The proposed checks address the measured driver, distinguish data defects from campaign performance, and connect each hypothesis to evidence that could support or refute it.
8. **Uncertainty and business usefulness**. The response identifies what an analyst can decide now and what remains uncertain. It describes exposure without invented savings or lift.

## Results

The offline contract run passed all six eligible fixtures and the insufficient-evidence gate. Automated API tests use mocked provider responses, including a strict JSON Schema response received through the official SDK. They exercise rejection of missing or invented references, unsupported numeric prose, quota and model errors, timeout handling, and regeneration. Offline fixtures establish contract behavior. Human review assesses model quality separately.

## Bounded live check

OpenAI model metadata confirmed access to `gpt-6-luna`. Detection run 1 supplied the three fictional findings below. The live check made one response request and one permitted retry per scenario. OpenAI returned token usage on all six calls, and each response reached local evidence validation. All six were rejected before publication with `AI_INVALID_OUTPUT` and are present in PostgreSQL as failed attempts.

| Scenario | Verified finding and review focus | Attempts | Input tokens | Output tokens | Estimated USD |
| --- | --- | --- | ---: | ---: | ---: |
| CPA deterioration | Finding 3, New Customer Acquisition. CPA moved from $49.02 to $58.90 (+20.15%), CPC from $1.84 to $2.05, and purchase CVR from 3.76% to 3.49%. Review whether both measured drivers are explained without causal claims. | 1, 2 | 4,066 | 1,734 | $0.001142 |
| Potential scaling | Finding 6, All-Weather Gear Shopping. Actual ROAS was 10.08× versus a 4.00× target. Review the proposed comparator and the distinction between average and marginal return. | 3, 4 | 4,356 | 2,772 | $0.001680 |
| Data quality | Finding 16, Alpine Collection Video. Five expected baseline days were missing from November 3–7, 2026. Review whether measurement repair takes priority over media changes. | 5, 6 | 4,268 | 1,694 | $0.001135 |
| **Total** | **Six calls, 18,890 tokens** | | **12,690** | **6,200** | **$0.003957** |

The estimate uses Standard short-context rates, including 6,336 cached input tokens and 6,336 thirty-minute cache-write tokens. The provider's invoice is authoritative. [GPT-6 Luna pricing](https://developers.openai.com/api/docs/models/gpt-6-luna) · [cache-write rates](https://developers.openai.com/api/docs/pricing)

The version used in this run kept a generic validation failure and discarded the rejected prose. Exact rejection reasons, recommendations and any specific unsupported claims are therefore unavailable for review. Subjective rubric entries remain pending. The subsequent implementation constrained the provider schema to verified paths and qualitative prose, supplied required policy citations explicitly, and added safe validation reasons to history. Those changes are exercised in tests with mock responses. A further paid run is needed to validate the revised contract with this model.

## Stabilization on November 24, 2026

The original six audit rows confirmed that all attempts reached provider completion and later failed generic local validation. Their text was discarded. Offline reproduction showed a contract mismatch in that release. Its provider schema accepted prose with correctly rounded numbers, while the local validator rejected any digits in prose. Additional local gates required policy citations and experiment conditions that the earlier schema did not fully express. The old audit cannot attribute those six failures to individual rules.

The stabilization fixtures use the fictional evidence exported from persisted findings 3, 6, and 16. Their responses were authored for the tests. They exercise exact references, decimal rounding, incorrect units and values, missing fields or optional measurements, incomplete replies, and narrowly detectable unsupported causal statements.

| Scenario | Attempt | Status | Input tokens | Output tokens | Estimated USD |
| --- | ---: | --- | ---: | ---: | ---: |
| CPA deterioration | 7 | Completed | 3,197 | 975 | $0.00088705 |
| Potential scaling | 9 | Completed | 3,431 | 1,477 | $0.00116730 |
| Data quality | 8 | Rejected by `NUMERIC_REFERENCE` | 3,317 | 822 | $0.00082555 |
| **Total** | **3 requests, zero retries** | **2 accepted, 1 rejected** | **9,945** | **3,274** | **$0.00287990** |

The estimate uses the provider's reported usage and Standard short-context rates, including 9,936 thirty-minute cache-write tokens and zero cache reads. [GPT-6 Luna pricing](https://developers.openai.com/api/docs/models/gpt-6-luna)

- The CPA analysis cited the rise in CPC and decline in purchase CVR as mathematical contributors. It proposed comparing matched-period search and auction reports and checking purchase tracking with the web analytics team. It rendered in Chrome and reopened without another generation request.
- The scaling analysis distinguished average attributed ROAS from marginal return. It proposed a small manual spend test against a comparable portion at existing spend, judged by attribution-matured ROAS with CPA and coverage guardrails.
- The data-quality response completed at OpenAI but failed at `/numeric_claims/1/reference` on `baseline.expected_days`, a valid numeric evidence ID. That rule combined catalog membership, duplication within numeric claims, and a requirement to repeat the ID in a second citation list. The artifact rules out catalog membership as the problem. It cannot distinguish the other two conditions for this rejected response. The final validator counts a verified numeric claim as its own citation and separately reports duplicate numeric claims. A regression fixture now supplies the expected-days figure only through the numeric claim and confirms it still resolves to the saved evidence. The original stabilization run reached its live call cap. The separately authorized follow-up appears below.

The two accepted results passed structural and numerical checks. The limited review above confirms what the responses said. Subjective rubric scores and deeper causal or experimental review remain pending. The rejected prose was discarded and has no recommendation available for review.

To verify the revised contract with an authorized live allowance, start a local API with one provider attempt per HTTP request. Use a second PowerShell window to execute the runner for exactly one current fictional finding. It refuses to repeat an existing attempt for that schema and gates the later cases on a completed CPA result. Confirm the CPA result in the Analyst before running the other cases. A failed CPA stops the live check.

```powershell
Set-Location backend
$env:AI_PROVIDER_MAX_ATTEMPTS = '1'
& ../.venv/Scripts/python.exe -m uvicorn app.main:app --port 8118
```

```powershell
Set-Location backend
& ../.venv/Scripts/python.exe -m evaluation.ai_live --scenario D-01 --execute --output ../.local/stabilization-d01.json
```

## D-06 follow-up on November 24, 2026

All 89 backend tests passed before the follow-up. One authorized live request for Alpine Collection Video, finding 16, used `gpt-6-luna` with zero retries. The result passed the validator and PostgreSQL saved it as completed analysis 10. Revalidating the saved output against its evidence snapshot passed, and `GET /api/v1/ai/analyses/10` returned the identical result after a backend restart. Read-only history checks confirmed that CPA and scaling still had their original completed analyses, 7 and 9.

D-06 selected `INVESTIGATE` and cited all five missing baseline dates from November 3 through November 7, plus the observed and expected coverage fields. It placed responsibility with the reporting or analytics owner to identify the gap, backfill missing records where possible, reconcile the totals, and rerun detection before using the baseline for performance decisions. The structured result proposed no media experiment. It cited `baseline.expected_days` through `evidence_references` and returned an empty `numeric_claims` list. The numeric-only citation path remains covered by the offline regression fixture.

The request used **4,142 tokens** across 3,317 input tokens, including 3,314 cache reads and zero cache writes, and 825 output tokens. Estimated cost at Standard short-context rates was **$0.00044594 USD**. [GPT-6 Luna pricing](https://developers.openai.com/api/docs/models/gpt-6-luna)

All three representative scenarios now have accepted live analyses. Acceptance establishes structure and evidence grounding. Human review and statistical validation remain separate.
