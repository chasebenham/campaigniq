import { Link } from "react-router"

import { PanelHeading, PlatformBadge } from "./shared"
import { Badge } from "./ui/badge"
import { Card } from "./ui/card"
import type { Finding, PeriodEvidence } from "@/lib/detection"
import { categories, severities, states } from "@/lib/detection"
import type { MetricKey } from "@/lib/api"
import { dateLabel, dateRange, formatContext, formatMetric, metricNames } from "@/lib/presentation"

const evidenceKeys: MetricKey[] = ["spend", "clicks", "impressions", "attributed_purchases", "attributed_purchase_value", "cpa", "roas", "purchase_cvr", "ctr", "cpc"]

export function FindingBadges({ finding }: { finding: Finding }) {
  return <div className="heading-badges">
    <Badge className={`finding-severity finding-${finding.severity.toLowerCase()}`}>{severities[finding.severity]} priority</Badge>
    <Badge className="status-completed">{states[finding.state]}</Badge>
  </div>
}

export function PeriodCard({ title, period }: { title: string; period: PeriodEvidence }) {
  return <Card className="evidence-card">
    <PanelHeading title={title} description={dateRange(period.start, period.end)} />
    <p className="evidence-coverage">{period.observed_days} of {period.calendar_days} reporting days observed</p>
    {period.fictional_days > 0 && <p className="evidence-coverage">{period.fictional_days === period.observed_days ? "Fictional seed evidence" : `Includes ${period.fictional_days} fictional seed days`}</p>}
    {period.missing_dates.length > 0 && <p className="evidence-coverage">Missing {period.missing_dates.map((day) => dateLabel(day)).join(", ")}</p>}
    <dl className="evidence-values">{evidenceKeys.map((key) => <div key={key}>
      <dt>{metricNames[key]}</dt><dd>{formatMetric(key, period.metrics?.[key])}</dd>
    </div>)}</dl>
  </Card>
}

const observationLabels: Record<string, string> = {
  cpa_change_pct: "CPA change",
  roas_target_deviation_pct: "ROAS deviation from target",
  cvr_change_pct: "Purchase CVR change",
  ctr_change_pct: "CTR change",
  cpc_change_pct: "CPC change",
  click_change_pct: "Click change",
  purchase_change_pct: "Purchase credit change",
  roas_change_pct: "ROAS change",
  spend_change_pct: "Spend change",
  flag_count: "Quality flag count",
  blocking_flag_count: "Blocking flag count",
  reported_zero_purchases: "Reported zero purchases",
  earlier_context: "Earlier coverage",
}
const percent = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 })
const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 })

export function evidenceLabel(key: string) {
  return observationLabels[key] ?? key.replaceAll("_", " ").replace(/pct$/, "(%)").replace(/^./, (value) => value.toUpperCase())
}

export function evidenceValue(key: string, value: unknown): string {
  if (value == null) return "—"
  if (typeof value === "boolean") return value ? "Yes" : "No"
  if (key.endsWith("_pct") && typeof value === "string") return `${percent.format(Number(value))}%`
  if (key.includes("spend") && typeof value === "string" && Number.isFinite(Number(value))) return money.format(Number(value))
  if (key === "earlier_context" && typeof value === "object" && "start" in value && "end" in value
    && "observed_days" in value && "expected_days" in value) {
    return `${dateRange(String(value.start), String(value.end))} · ${value.observed_days} of ${value.expected_days} days`
  }
  return typeof value === "object" ? JSON.stringify(value) : String(value)
}

function EvidenceValues({ values }: { values: Record<string, unknown> }) {
  return <dl className="evidence-values">{Object.entries(values).map(([key, value]) => <div key={key}>
    <dt>{evidenceLabel(key)}</dt><dd>{evidenceValue(key, value)}</dd>
  </div>)}</dl>
}

export function FindingEvidence({ finding }: { finding: Finding }) {
  const campaign = finding.campaign_snapshot
  const range = new URLSearchParams({
    start_date: finding.baseline_evidence?.start ?? finding.current_evidence.start,
    end_date: finding.current_evidence.end,
  })
  return <>
    <Card className="evidence-card">
      <PanelHeading title="Verified finding" description={finding.classification_reason}>
        <FindingBadges finding={finding} />
      </PanelHeading>
      <div className="finding-meta">
        <Link className="text-link" to={`/campaigns/${finding.campaign_id}?${range}`}>{campaign.campaign_name}</Link>
        <PlatformBadge platform={campaign.platform} />
        <span>{finding.policy_id} · {categories[finding.category]}</span>
        <span>Evidence {finding.evidence_quality.toLowerCase()}</span>
      </div>
      <EvidenceValues values={{
        ...finding.observations,
        "Target CPA": formatMetric("cpa", campaign.target_cpa),
        "Target ROAS": formatMetric("roas", campaign.target_roas),
      }} />
    </Card>
    <div className="evidence-grid">
      <PeriodCard title="Current period" period={finding.current_evidence} />
      {finding.baseline_evidence && <PeriodCard title="Baseline period" period={finding.baseline_evidence} />}
    </div>
    <div className="evidence-grid">
      <Card className="evidence-card">
        <PanelHeading title="Rule thresholds" description={`Policy version ${finding.policy_version}`} />
        <EvidenceValues values={finding.thresholds} />
      </Card>
      <Card className="evidence-card">
        <PanelHeading title="Reporting definition and limitations" />
        <div className="evidence-body">
          {finding.reporting_context.map((context) => <p key={formatContext(context)}>{formatContext(context)}</p>)}
          {finding.limitations.map((item) => <p key={item}>{item}</p>)}
        </div>
      </Card>
    </div>
    {finding.data_quality_flags.length > 0 && <Card className="evidence-card">
      <PanelHeading title="Related data-quality warnings" />
      <ul className="quality-list">{finding.data_quality_flags.map((flag) => <li key={`${flag.period}-${flag.code}`}>
        <strong>{flag.period[0].toUpperCase() + flag.period.slice(1)} · {flag.blocking ? "Blocker" : "For review"}</strong>
        <p>{flag.message}</p>
        {flag.dates.length > 0 && <small>{flag.dates.map((value) => dateLabel(value)).join(", ")}</small>}
      </li>)}</ul>
    </Card>}
  </>
}

export function FindingMetric({ finding }: { finding: Finding }) {
  const metrics = finding.current_evidence.metrics
  switch (finding.policy_id) {
    case "D-01": return <>{formatMetric("cpa", metrics?.cpa)} CPA · {evidenceValue("cpa_change_pct", finding.observations.cpa_change_pct)}</>
    case "D-02":
    case "D-05": return <>{formatMetric("roas", metrics?.roas)} ROAS · {evidenceValue("roas_target_deviation_pct", finding.observations.roas_target_deviation_pct)} vs target</>
    case "D-03": return <>{formatMetric("purchase_cvr", metrics?.purchase_cvr)} CVR · {evidenceValue("cvr_change_pct", finding.observations.cvr_change_pct)}</>
    case "D-04": return <>{formatMetric("spend", metrics?.spend)} spend · 0 purchases</>
    case "D-06": return <>{finding.data_quality_flags[0]?.message ?? "Review reporting coverage."}</>
  }
}
