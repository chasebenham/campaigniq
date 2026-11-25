"""The versioned executive template shared by the browser and PDF renderer."""

from datetime import datetime
from decimal import Decimal

from app.briefs.schemas import Block, Document, Draft, Section, Table

PLATFORMS = {"GOOGLE_ADS": "Google Ads", "META_ADS": "Meta Ads"}
RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "INFORMATIONAL": 3}
METRICS = (
    ("spend", "Spend"), ("impressions", "Impressions"), ("clicks", "Clicks"),
    ("attributed_purchases", "Attributed purchases"), ("attributed_purchase_value", "Attributed value"),
    ("ctr", "CTR"), ("cpc", "CPC"), ("cpa", "CPA"), ("roas", "ROAS"),
)
FOCUS = {
    "D-01": ("cpa", "cpc", "purchase_cvr", "spend", "attributed_purchases"),
    "D-02": ("roas", "spend", "attributed_purchase_value"),
    "D-03": ("purchase_cvr", "ctr", "cpc", "cpa", "clicks", "attributed_purchases"),
    "D-04": ("spend", "attributed_purchases"),
    "D-05": ("roas", "cpa", "spend", "attributed_purchases"),
    "D-06": (),
}
ATTRIBUTION_LIMIT = "Purchase credit and value are platform-attributed. This evidence cannot establish incremental revenue, profit, or unique customer counts."


def money(value):
    return "$" + f"{Decimal(value):,.2f}" if value is not None else "Unavailable"


def number(value, suffix=""):
    if value is None:
        return "Unavailable"
    return f"{Decimal(value):,.2f}".rstrip("0").rstrip(".") + suffix


def date_range(row):
    return f"{row['start']} to {row['end']}"


def human(value: str):
    return value.replace("_", " ").capitalize()


def metric(key, value):
    if key in ("spend", "cpc", "cpa", "attributed_purchase_value", "value"):
        return money(value)
    if key == "roas":
        return f"{Decimal(value):.2f}x" if value is not None else "Unavailable"
    if key in ("ctr", "purchase_cvr"):
        return f"{Decimal(value):.2f}%" if value is not None else "Unavailable"
    return number(value)


def context_lines(contexts):
    return [" / ".join(human(str(row[key])) for key in
                       ("conversion_action", "attribution_method", "attribution_window", "date_basis"))
            for row in contexts]


def overview(evidence):
    report = evidence["performance"]
    portfolio = report["portfolio"]
    platforms = {row["platform"]: row for row in report["platforms"]}
    series = [portfolio.get("metrics") or {}, *(platforms.get(key, {}).get("metrics") or {} for key in PLATFORMS)]
    ratio_note = "CPA and ROAS use summed spend, attributed credit and value. A value is unavailable when inputs, reporting definitions or denominators do not support it."
    if portfolio["platform_attributed_overlap"]:
        ratio_note += " Google Ads and Meta Ads attribution can overlap."
    reporting = (
        f"{report['days_with_data']} of {report['calendar_days']} calendar dates have observations. "
        f"{report['expected_days'] - report['missing_days']:,} of {report['expected_days']:,} expected campaign-day reports are present."
    )
    latest = portfolio["latest_import_at"]
    paragraphs = [reporting]
    if latest:
        paragraphs.append(f"Latest contributing import {latest[:10]} UTC.")
    if contexts := context_lines(portfolio["attribution_contexts"]):
        if len(contexts) == 1 and all(row["attribution_contexts"] == portfolio["attribution_contexts"] for row in platforms.values()):
            paragraphs.append(f"Reporting definition shared by the displayed platform totals: {contexts[0]}.")
        else:
            paragraphs.append(f"Portfolio reporting definitions: {' | '.join(contexts)}.")
    for key, row in platforms.items():
        if contexts := context_lines(row["attribution_contexts"]):
            if row["attribution_contexts"] != portfolio["attribution_contexts"] or len(contexts) != 1:
                paragraphs.append(f"{PLATFORMS[key]} reporting definitions: {' | '.join(contexts)}.")
    tables = [Table(headers=["Metric", "Portfolio", *PLATFORMS.values()], rows=[
        [label, *(metric(key, item.get(key)) for item in series)] for key, label in METRICS
    ], caption=ratio_note)]
    if len(report["trend"]) > 1:
        tables.append(Table(headers=["Reporting interval", "Observed days", "Observed spend"], rows=[
            [date_range(row), str(row["days"]), money(row["spend"])] for row in report["trend"]
        ], caption="Spend grouped into consecutive seven-day intervals. Missing dates are excluded."))
    return Section(title="Marketing Performance Overview", blocks=[Block(source="verified", paragraphs=paragraphs, tables=tables)])


def thresholds(values):
    return ", ".join(
        f"{name.removesuffix('_pct').replace('_', ' ')} "
        f"{money(value) if name.endswith('_spend') else number(value, '%' if name.endswith('_pct') else '')}"
        for name, value in sorted(values.items()) if value is not None
    )


def finding_block(finding):
    campaign = finding["campaign_snapshot"]
    current, baseline = finding["current_evidence"], finding["baseline_evidence"]
    descriptions = [
        f"{campaign['campaign_name']} · {PLATFORMS.get(campaign['platform'], campaign['platform'])} · {finding['severity'].title()} · {human(finding['category'])}",
        f"{finding['policy_id']} v{finding['policy_version']} · Finding #{finding['id']} · Run #{finding['run_id']} · Evidence {human(finding['evidence_quality']).lower()} · {finding['state'].title()}",
        f"Evaluated {date_range(current)}." + (f" Comparison {date_range(baseline)}." if baseline else ""),
        finding["classification_reason"],
    ]
    if definitions := context_lines(finding["reporting_context"]):
        descriptions.append("Reporting definitions: " + " | ".join(definitions) + ".")
    if rule_thresholds := thresholds(finding["thresholds"]):
        descriptions.append("Rule thresholds: " + rule_thresholds + ".")
    deltas = {key: value for key, value in finding["observations"].items() if key.endswith("_pct")}
    if deltas:
        descriptions.append("Observed relative changes: " + thresholds(deltas) + ".")
    rows = []
    if finding["policy_id"] == "D-06":
        for period in [row for row in (current, baseline) if row]:
            rows.append([date_range(period), str(period["observed_days"]), str(period["expected_days"])])
        table = Table(headers=["Reporting window", "Observed days", "Expected days"], rows=rows)
    else:
        targets = campaign.get("target_cpa"), campaign.get("target_roas")
        labels = dict(METRICS, purchase_cvr="Purchase CVR")
        for key in FOCUS[finding["policy_id"]]:
            target = targets[0] if key == "cpa" else targets[1] if key == "roas" else None
            cells = [labels[key], metric(key, (current.get("metrics") or {}).get(key))]
            if baseline:
                cells.append(metric(key, (baseline.get("metrics") or {}).get(key)))
            rows.append([*cells, metric(key, target) if target is not None else "-"])
        table = Table(headers=["Measured metric", "Evaluated", *(["Comparison"] if baseline else []), "Target"], rows=rows)
    flags = [f"{human(flag['period'])}: {flag['message']}" +
             (f" Dates: {', '.join(flag['dates'])}." if flag.get("dates") else "")
             for flag in finding["data_quality_flags"]]
    return Block(title=finding["summary"], source="verified", paragraphs=descriptions,
                 bullets=[*flags, *(item for item in finding["limitations"] if item != ATTRIBUTION_LIMIT)], tables=[table])


def analysis_block(item, analysis):
    output = analysis["output"]
    suggestions = " ".join(output["possible_explanations"])
    missing = " ".join(output["missing_information"])
    return Block(title=f"{item['finding']['campaign_snapshot']['campaign_name']} · {item['finding']['policy_id']}",
                 source="ai", paragraphs=[
                     f"Accepted AI Analyst #{analysis['id']} · {analysis['model']} · Schema {analysis['schema_version']}"
                     + (" · Historical evidence" if analysis["historical"] else ""),
                     output["executive_summary"], output["business_impact_assessment"],
                     f"Recommended action: {human(output['recommended_action_type'])}. {output['recommended_action']}",
                     *([output["action_rationale"]] if output.get("action_rationale") else []),
                 ], bullets=[value for value in [
                     f"Unconfirmed hypotheses: {suggestions}" if suggestions else "",
                     f"Missing evidence: {missing}" if missing else "", output["confidence_rationale"],
                     *output["risks_and_limitations"],
                     "Evidence references: " + ", ".join(analysis["references"]),
                 ] if value])


def experiment_block(item, analysis):
    output = analysis["output"]
    experiment = output["proposed_experiment"]
    bullets = [
        ("Hypothesis", output.get("experiment_hypothesis")), ("Proposed change", experiment.get("proposed_change") or experiment["design"]),
        ("Comparator", experiment.get("comparison")), ("Scope", experiment["audience_or_scope"]),
        ("Primary success metric", output["primary_success_metric"]), ("Secondary metrics", ", ".join(output["secondary_metrics"])),
        ("Guardrail metrics", ", ".join(experiment.get("guardrail_metrics", []))), ("Guardrails", experiment["guardrails"]),
        ("Measurement window", experiment["duration"]), ("Decision rule", experiment["decision_rule"]),
        ("Risks and limitations", "; ".join(output["risks_and_limitations"])),
    ]
    return Block(title=f"{item['finding']['campaign_snapshot']['campaign_name']} · Proposed by AI Analyst #{analysis['id']}",
                 source="ai", paragraphs=["Proposed investigation or experiment. Results are pending."],
                 bullets=[f"{label}: {value}" for label, value in bullets if value])


def budget_section(budget):
    result = budget["result"]
    plan = budget["plan"]
    campaigns = {row["campaign_id"]: row for row in result["benchmarks"]}
    allocation = []
    for line in result["allocation"]:
        row = campaigns[line["campaign_id"]]
        allocation.append([row["campaign_name"], money(line["normalized"]["spend"]),
                           money(line["planned_spend"]), number(line["planned_share_pct"], "%")])
    case_rows = []
    assumption_rows = []
    for name in ("conservative", "base", "optimistic"):
        row = result["scenarios"][name]["portfolio"]
        case_rows.append([name.title(), number(row["purchases"]), money(row["value"]), money(row["cpa"]), metric("roas", row["roas"])])
        assumption = plan["assumptions"][name]
        assumption_rows.append([name.title(), number(assumption["cpa_change_pct"], "%"),
                                number(assumption["marginal_cpa_change_pct"], "%"),
                                number(assumption["value_per_purchase_change_pct"], "%")])
    return Section(title="Budget Scenario Analysis", blocks=[Block(
        title=budget["name"], source="modeled", paragraphs=[
            f"Saved scenario #{budget['id']} · Model {budget['model_version']} · Total hypothetical budget {money(budget['total_budget'])}.",
            ("Stale reference evidence. The original saved scenario is shown." if budget["status"] == "STALE" else "Saved reference evidence was current when collected."),
            f"Historical reference {date_range(budget['reference'])}. Planning {date_range(budget['planning'])}.",
            "Modeled purchase credit and value are platform-attributed. Marginal auction response, profit, and incrementality require separate evidence.",
        ], tables=[
            Table(headers=["Campaign", "Normalized history", "Proposed spend", "Planned share"], rows=allocation),
            Table(headers=["Case", "Purchase credit", "Attributed value", "CPA", "ROAS"], rows=case_rows),
            Table(headers=["Case", "Base CPA change", "Marginal CPA change", "Value per purchase"], rows=assumption_rows),
        ], bullets=[
            (f"{campaigns[row['campaign_id']]['campaign_name']}: " if row["campaign_id"] else "") + row["message"]
            for row in result["warnings"]
        ],
    )])


def narrative_block(content, generation=None, *, title=None, summary=False):
    if not generation:
        return Block(title=title, source="management", paragraphs=[content])
    edited = generation["authorship"] == "AI_EDITED_BY_MANAGEMENT"
    kind = "summary" if summary else "draft"
    label = f"Management-edited AI {kind}" if edited else f"AI-generated {kind}"
    notes = [f"{label} · {generation['model']} · proposal #{generation['id']}."]
    if generation.get("stale"):
        notes.append("Drafted against earlier evidence. Review it alongside the current report sources.")
    return Block(title=title, source="management" if edited else "ai", paragraphs=[content, *notes],
                 bullets=["Evidence references: " + ", ".join(generation["references"])])


def executive(draft, data, generation):
    portfolio = data["performance"]["portfolio"]
    if draft.narrative.executive_summary:
        return [narrative_block(draft.narrative.executive_summary, generation, summary=True)]
    totals = portfolio.get("metrics") or {}
    observed = (f"Observed paid-media spend was {money(totals['spend'])} across the selected dates." if "spend" in totals
                else "Verified performance totals are unavailable for the selected dates.")
    if totals.get("roas") is not None:
        observed += f" Platform-attributed ROAS was {metric('roas', totals['roas'])}."
    priorities = []
    selected = sorted((item["finding"] for item in data["findings"]), key=lambda finding: RANK[finding["severity"]])
    actions = {
        "DATA_QUALITY": "Reconcile the available reporting before drawing performance conclusions",
        "PERFORMANCE_RISK": "Investigate the observed risk",
        "OPTIMIZATION_OPPORTUNITY": "Evaluate whether a controlled test is warranted",
    }
    for category, action in actions.items():
        if finding := next((item for item in selected if item["category"] == category), None):
            context = finding["state"].lower()
            campaign = finding["campaign_snapshot"]["campaign_name"]
            priorities.append(f"{action} for {campaign} ({finding['summary']}, {context} finding #{finding['id']}).")
    limits = [data["warnings"][0]] if data["warnings"] else []
    return [Block(source="verified", paragraphs=[observed, *limits], bullets=priorities)]


def make_document(draft: Draft, evidence: dict, generated: datetime, generation: dict | None, commentary: dict) -> Document:
    provenance = evidence["performance"]["portfolio"]
    seeded = provenance["fictional_record_count"]
    sources = (f"CampaignIQ reporting store · {provenance['record_count']:,} campaign-day records · "
               f"{seeded:,} fictional seed records and {provenance['record_count'] - seeded:,} uploaded records.")
    items = sorted(evidence["findings"], key=lambda item: RANK[item["finding"]["severity"]])
    accepted = [(item, item["analysis"]) for item in items if item["analysis"]]
    findings = [finding_block(item["finding"]) for item in items]
    interpretations = [analysis_block(item, analysis) for item, analysis in accepted]
    experiments = [experiment_block(item, analysis) for item, analysis in accepted if analysis["output"]["proposed_experiment"]]
    if draft.narrative.recommendations:
        interpretations.append(narrative_block(draft.narrative.recommendations, commentary.get("recommendations"), title="Strategic recommendations"))
    if draft.narrative.commentary:
        interpretations.append(narrative_block(draft.narrative.commentary, commentary.get("commentary"), title="Management commentary"))
    if draft.narrative.experiment:
        experiments.append(narrative_block(draft.narrative.experiment, commentary.get("experiment"), title="Management proposal"))
    sections = [
        Section(title="Executive Summary", blocks=executive(draft, evidence, commentary.get("executive_summary") or generation)),
        overview(evidence),
        Section(title="Prioritized Findings", blocks=findings or [Block(paragraphs=["This brief contains no selected detection findings."])]),
        Section(title="Strategic Interpretation", blocks=interpretations or [Block(paragraphs=["No accepted AI interpretation or management commentary was included."])]),
        Section(title="Proposed Marketing Experiments", blocks=experiments or [Block(paragraphs=["No experiment proposal was included."])]),
    ]
    if evidence["budget"]:
        sections.append(budget_section(evidence["budget"]))
    risks = [
        "Attributed purchase credit and value describe platform reporting. Profit, causal effects, and incremental revenue require separate evidence.",
        *evidence["warnings"],
    ]
    if accepted or generation or commentary:
        risks.append("AI interpretations describe hypotheses and proposed actions. Verify missing evidence before acting.")
    sections.append(Section(title="Risks, Limitations & Next Decisions", blocks=[
        Block(bullets=risks),
        *([narrative_block(draft.narrative.next_decisions, commentary.get("next_decisions"), title="Next decisions")] if draft.narrative.next_decisions else []),
    ]))
    document = Document(title=draft.title, period=draft.sources.period, generated_at=generated, provenance=sources, sections=sections)
    return document.model_copy(update={"template_version": "1.1.0"}) if commentary else document
