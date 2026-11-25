import { useState } from "react"
import { Link } from "react-router"
import { CircleAlert, Info } from "lucide-react"

import { PanelHeading, PlatformBadge } from "@/components/shared"
import { Card } from "@/components/ui/card"
import type { Decimal, MetricKey } from "@/lib/api"
import { cases, caseNames, type Benchmark, type BudgetCase, type Calculation, type Outcome, type Plan } from "@/lib/budget"
import { dateRange, formatContext, formatMetric } from "@/lib/presentation"

const credit = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 })
const share = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
export const percent = (value: Decimal) => `${share.format(value)}%`
export const money = (value: Decimal | null | undefined) => formatMetric("spend", value)
const fields = [
  ["spend", "Spend", "spend"], ["purchases", "Attributed purchase credit", "attributed_purchases"],
  ["value", "Attributed value", "attributed_purchase_value"], ["cpa", "CPA", "cpa"], ["roas", "ROAS", "roas"],
] as const

function amount(key: MetricKey, value: Decimal | null | undefined) {
  return key === "attributed_purchases" && value != null ? credit.format(value) : formatMetric(key, value)
}

function change(key: MetricKey, value: Decimal | null) {
  return `${Number(value) > 0 ? "+" : ""}${amount(key, value)}`
}

export function OutcomeCells({ data, signed = false }: { data: Outcome; signed?: boolean }) {
  return <>{fields.map(([key, , format]) => <td key={key}>{signed ? change(format, data[key]) : amount(format, data[key])}</td>)}</>
}

function OutcomeHeaders() {
  return <>{fields.map(([key, label]) => <th key={key} scope="col">{label}</th>)}</>
}

export function HistoricalTable({ rows }: { rows: Benchmark[] }) {
  return <div className="table-scroll" role="region" tabIndex={0} aria-label="Selected campaign historical benchmarks">
    <table className="data-table">
      <thead><tr>{["Campaign", "Observed spend", "Purchase credit", "Attributed value", "CPA", "ROAS", "Daily spend", "Coverage"].map(label =>
        <th key={label} scope="col">{label}</th>)}</tr></thead>
      <tbody>{rows.map(row => <tr key={row.campaign_id}>
        <th scope="row"><Link className="text-link" to={`/campaigns/${row.campaign_id}`}>{row.campaign_name}</Link>
          <small className="table-secondary"><PlatformBadge platform={row.platform} /></small></th>
        <td>{money(row.period.metrics?.spend)}</td>
        <td>{amount("attributed_purchases", row.period.metrics?.attributed_purchases)}</td>
        <td>{money(row.period.metrics?.attributed_purchase_value)}</td>
        <td>{formatMetric("cpa", row.period.metrics?.cpa)}</td>
        <td>{formatMetric("roas", row.period.metrics?.roas)}</td>
        <td>{money(row.average_daily_spend)}</td>
        <td>{row.period.observed_days} of {row.period.expected_days} expected days
          <small className={`table-secondary ${row.eligible ? "" : "budget-blocked"}`}>{row.eligible ? "Eligible" : "Blocked"}</small></td>
      </tr>)}</tbody>
    </table>
  </div>
}

export function BenchmarkNotes({ rows }: { rows: Benchmark[] }) {
  return <div className="budget-panel-body budget-benchmark-notes">
    {rows.map(row => <details key={row.campaign_id}>
      <summary>{row.campaign_name} <span>{row.eligible ? "Eligible" : "Blocked"}</span></summary>
      <div>
        <p>{row.period.observed_days} observed / {row.period.expected_days} expected / {row.period.calendar_days} selected calendar days.
          {row.period.fictional_days > 0 && ` Includes ${row.period.fictional_days} fictional reporting days.`}</p>
        <p>{row.attribution_contexts.length ? row.attribution_contexts.map(formatContext).join(" | ") : "No attribution definition available."}</p>
        {row.blockers.length > 0 && <ul>{row.blockers.map(message => <li key={message}>{message}</li>)}</ul>}
        {row.flags.filter(flag => !flag.blocking).map(flag => <p key={flag.code}>{flag.message}</p>)}
        {row.period.missing_dates.length > 0 && <p>Missing dates · {row.period.missing_dates.join(", ")}</p>}
      </div>
    </details>)}
  </div>
}

const assumptionLabels = {
  cpa_change_pct: "Base CPA adjustment",
  marginal_cpa_change_pct: "Extra CPA above historical spend",
  value_per_purchase_change_pct: "Attributed value per purchase adjustment",
} as const

export function BudgetResults({ result, plan, frozen = false }: { result: Calculation; plan: Plan; frozen?: boolean }) {
  const [active, setActive] = useState<BudgetCase>("base")
  const modeled = result.scenarios[active]
  const campaigns = new Map(result.benchmarks.map(row => [row.campaign_id, row.campaign_name]))
  const maximum = Math.max(0, ...cases.map(name => Number(result.scenarios[name].portfolio.value ?? 0)))
  return <div className="budget-results">
    <Card className="table-card">
      <PanelHeading title="Historical baseline" description={`${dateRange(plan.reference.start, plan.reference.end)} · ${result.reference_days} reference days`} />
      {frozen && <HistoricalTable rows={result.benchmarks} />}
      <div className="table-scroll"><table className="data-table" aria-label="Historical baseline">
        <thead><tr><th scope="col">Comparison</th><OutcomeHeaders /></tr></thead>
        <tbody>
          <tr><th scope="row">Historical observed</th><OutcomeCells data={result.observed} /></tr>
          <tr><th scope="row">Normalized to {result.planning_days} planning days<small className="table-secondary">Eligible campaigns only</small></th>
            <OutcomeCells data={result.normalized} /></tr>
        </tbody>
      </table></div>
    </Card>
    <Card className="table-card">
      <PanelHeading title="Allocation comparison" description="Observed shares use reporting-period spend. Differences use shares and spend normalized to the planning period." />
      <div className="table-scroll" role="region" tabIndex={0} aria-label="Historical and planned allocation">
        <table className="data-table">
          <thead><tr>{["Campaign", "Observed share", "Normalized spend / share", "Planned spend / share", "Spend change", "Share change"].map(label =>
            <th scope="col" key={label}>{label}</th>)}</tr></thead>
          <tbody>{result.allocation.map(row => <tr key={row.campaign_id}>
            <th scope="row">{campaigns.get(row.campaign_id)}</th><td>{percent(row.observed_share_pct)}</td>
            <td>{money(row.normalized.spend)} · {percent(row.normalized_share_pct)}</td>
            <td>{money(row.planned_spend)} · {percent(row.planned_share_pct)}</td>
            <td>{change("spend", row.spend_change)}</td>
            <td>{Number(row.share_change_pct_points) > 0 ? "+" : ""}{share.format(row.share_change_pct_points)} pp</td>
          </tr>)}</tbody>
        </table>
      </div>
    </Card>
    <Card className="table-card budget-modeled">
      <PanelHeading title="Modeled outcomes" description={`${dateRange(plan.planning.start, plan.planning.end)} · Hypothetical platform-attributed results`} />
      <div className="budget-panel-body budget-case-grid">
        {cases.map(name => <button key={name} type="button" className="budget-case-card" aria-pressed={active === name} onClick={() => setActive(name)}>
          <span>{caseNames[name]}</span><strong>{money(result.scenarios[name].portfolio.value)}</strong><small>Modeled attributed value</small>
          {maximum > 0 && result.scenarios[name].portfolio.value != null && <span className="budget-track" aria-hidden="true">
            <span style={{ width: `${100 * Number(result.scenarios[name].portfolio.value) / maximum}%` }} />
          </span>}
        </button>)}
      </div>
      <div className="table-scroll"><table className="data-table" aria-label={`${caseNames[active]} portfolio results`}>
        <thead><tr><th scope="col">Portfolio</th><OutcomeHeaders /></tr></thead>
        <tbody>
          <tr><th scope="row">{caseNames[active]} modeled</th><OutcomeCells data={modeled.portfolio} /></tr>
          <tr><th scope="row">Change vs. normalized history</th><OutcomeCells data={modeled.delta} signed /></tr>
          {active !== "base" && <tr><th scope="row">Change vs. Base</th><OutcomeCells data={modeled.versus_base} signed /></tr>}
        </tbody>
      </table></div>
      <div className="budget-panel-body budget-case-inputs">
        {Object.entries(plan.assumptions[active]).map(([id, value]) => <span key={id}>
          {assumptionLabels[id as keyof typeof assumptionLabels]} <strong>{Number(value) > 0 ? "+" : ""}{value}%</strong>
        </span>)}
      </div>
    </Card>
    <Card className="table-card">
      <PanelHeading title={`${caseNames[active]} campaign results`} description="Each campaign’s change uses its own historical rate normalized to the planning period." />
      <div className="table-scroll" role="region" tabIndex={0} aria-label="Modeled campaign results">
        <table className="data-table">
          <thead><tr><th scope="col">Campaign</th><th scope="col">Comparison</th><OutcomeHeaders /></tr></thead>
          <tbody>{modeled.campaigns.flatMap(row => [
            <tr key={row.campaign_id}><th scope="row">{campaigns.get(row.campaign_id)}</th>
              <td>{result.benchmarks.find(item => item.campaign_id === row.campaign_id)?.eligible ? "Modeled" : "Excluded"}</td>
              <OutcomeCells data={row.modeled} /></tr>,
            <tr key={`delta-${row.campaign_id}`} className="budget-delta-row"><td /><th scope="row">Change vs. history</th>
              <OutcomeCells data={row.delta} signed /></tr>,
          ])}</tbody>
        </table>
      </div>
    </Card>
    <Card className="table-card">
      <PanelHeading title="Uncertainty and limitations" description="Modeled credit may overlap across platforms. Profit, incrementality and actual auction response require separate evidence." />
      {result.warnings.length ? <ul className="budget-panel-body budget-warnings">{result.warnings.map(warning => <li key={`${warning.code}-${warning.campaign_id}-${warning.scenario}`}>
        {warning.severity === "warning" ? <CircleAlert size={16} aria-hidden="true" /> : <Info size={16} aria-hidden="true" />}
        <div>
          {(warning.campaign_id || warning.scenario) && <strong>{warning.campaign_id ? campaigns.get(warning.campaign_id) : caseNames[warning.scenario!]}</strong>}
          <p>{warning.message}</p>
        </div>
      </li>)}</ul> : <p className="budget-panel-body support-text">No additional warnings for this calculation.</p>}
      {frozen && <BenchmarkNotes rows={result.benchmarks} />}
    </Card>
  </div>
}
