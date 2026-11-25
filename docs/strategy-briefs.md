# Strategy Briefs

Strategy Briefs turns CampaignIQ measurements into a versioned leadership report for fictional Northstar Outfitters. The template covers the reporting context, executive summary, portfolio and platform performance, prioritized findings, strategic interpretation, proposed experiments, optional Budget Lab analysis, and risks and decisions.

## Create and export a brief

1. Open **Strategy Briefs** and select **Create Strategy Brief**. Enter a title and an inclusive reporting period. The builder suggests up to three findings from the current applicable detection run. Explicitly choose the evidence to include.
2. Select up to eight findings. Each evaluated window must fit inside the report period. Historical comparison windows may precede it and retain their own dates. Choose a completed AI Analyst interpretation for its own finding, or select verified evidence only.
3. To attach hypothetical budget outcomes, select a saved Budget Lab scenario. Its historical and planning periods stay separate from the report dates. Review and acknowledge any historical or stale sources before collecting them.
4. Write an executive summary or leave the field blank for an evidence-based default. Add recommendations, management context, a proposed experiment, or next decisions as needed.
5. Select **Preview report**, review the evidence and limitations, and choose **Save strategy brief**. Open the saved version and select **Export PDF**. Previous versions also have separate export links.
6. Use **Revise brief** to save another version. Commentary-only edits preserve the same evidence. Select **Refresh verified evidence**, or change the sources, to collect a new snapshot.

Contextual links from Insights, completed AI Analyst results, and saved Budget Lab scenarios carry source IDs to the builder. Inclusion still requires a deliberate selection. [Reporting methodology](report-methodology.md) · [PDF export](pdf-export.md)

## Optional executive synthesis

In the builder, choose **Generate with AI** beside any commentary field or **Draft All Five** to draft each field in one request. Existing text is listed for confirmation before generation replaces it. You can edit the result, keep a previous draft, or regenerate after changing the report dates or sources. Preview and save explicitly to include the reviewed text in a report version. Earlier drafts retain their evidence warnings.

On the current version of a report with current evidence, **Generate Executive Summary with AI** sends a compact server-built evidence catalog to the configured model. The AI proposal remains separate until you choose **Use proposal in a revision** and save. A modified proposal is labeled management-edited. The feature uses the existing `AI_ANALYSIS_ENABLED`, `OPENAI_API_KEY`, and `OPENAI_MODEL` settings. It shares the hourly request budget, provider timeout, and transient retry policy with AI Analyst. Opening, previewing, saving, and exporting briefs work offline. [AI Analyst configuration](ai-analyst.md)

## API

Routes below use `/api/v1/strategy-briefs`. FastAPI exposes request and response schemas at `/docs`.

| Method and path | Purpose |
| --- | --- |
| `GET /` and `POST /` | List briefs and save the first reviewed version |
| `GET /defaults` | Suggest reporting dates and an applicable current run |
| `GET /sources?start=…&end=…` | Page findings inside the date range and list their accepted analyses |
| `POST /preview` | Preview a new brief and obtain its evidence fingerprint |
| `POST /draft-commentary` | Draft a single commentary field or all five from the submitted source selections |
| `GET /{id}` and `PUT /{id}` | Retrieve the latest snapshot and append a revision |
| `POST /{id}/preview` | Preview a revision against its selected base version |
| `GET /{id}/versions` | Page immutable versions |
| `GET /{id}/versions/{version}` | Retrieve the selected saved version |
| `POST /{id}/generate-summary` | Explicitly request or retrieve synthesis for the version in the request |
| `GET /{id}/export/pdf?version=N` | Export that exact saved version |

## Fictional example

**November leadership brief · November 3–16, 2026**

- **Observed performance** — $62,870.17 in reported spend and $212,118.51 in platform-attributed purchase value across 219 observed campaign-day records. Five expected records were absent.
- **Priorities** — Investigate New Customer Acquisition’s observed CPA increase from $49.02 to $58.90. Reconcile Alpine Collection Video’s five missing baseline reporting days. Consider examining a controlled scaling test for All-Weather Gear Shopping after reviewing measurement and guardrails.
- **Potential experiment** — After reporting gaps are reconciled, compare a limited allocation change with the existing allocation. Use attributed CPA as the primary metric, ROAS as secondary, and spend and purchase credit as guardrails. Review only after complete mature reporting and an agreed evidence threshold.
- **Budget context** — The example attaches a $24,000 hypothetical allocation. The three modeled outcomes depend on the chosen CPA and attributed-value assumptions. [Budget methodology](budget-methodology.md)

The worked example uses the fictional seed and an existing accepted interpretation. The proposal describes a decision to investigate, with no test result or business outcome implied.
