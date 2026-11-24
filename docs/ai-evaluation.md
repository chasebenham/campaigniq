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

To reproduce with a new authorized allowance, start a local API with one provider attempt per HTTP request. Use a second PowerShell window to execute the bounded runner. The runner selects up to three current fictional findings, uses normal cache semantics, and retries only eligible failures once.

```powershell
Set-Location backend
$env:AI_PROVIDER_MAX_ATTEMPTS = '1'
& ../.venv/Scripts/python.exe -m uvicorn app.main:app --port 8118
```

```powershell
Set-Location backend
& ../.venv/Scripts/python.exe -m evaluation.ai_live --execute --output ../.local/phase2b-live-next.json
```
