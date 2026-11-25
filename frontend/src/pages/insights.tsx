import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Activity, CircleAlert } from "lucide-react"
import { Link, useParams } from "react-router"

import { FilterBar, SelectField, useReportFilters } from "@/components/filters"
import { FindingEvidence, FindingMetric } from "@/components/finding-evidence"
import { Empty, ErrorPanel, Loading, PageHeading, Pagination, PanelHeading, PlatformBadge } from "@/components/shared"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { getCampaignOptions } from "@/lib/api"
import { budgetFindingLink } from "@/lib/budget"
import { categories, detection, policies, severities, states, type DetectionRun, type Finding } from "@/lib/detection"
import { dateLabel, dateRange } from "@/lib/presentation"

const summaryLabels = { ...categories, INSUFFICIENT_EVIDENCE: "Insufficient evidence / suppressed" } as const

export function Insights() {
  const query = useQueryClient()
  const { filters, invalid, params, change, setFilter } = useReportFilters()
  const options = useQuery({ queryKey: ["campaign-options"], queryFn: ({ signal }) => getCampaignOptions(signal) })
  const summary = useQuery({ queryKey: ["detection", "summary"], queryFn: ({ signal }) => detection.summary(signal) })
  const [historyPage, setHistoryPage] = useState(1)
  const [auditRun, setAuditRun] = useState<number | null>(null)
  const [auditPage, setAuditPage] = useState(1)
  const history = useQuery({ queryKey: ["detection", "runs", historyPage], queryFn: ({ signal }) => detection.runs(historyPage, signal) })
  const listFilters = {
    ...filters, policy_id: params.get("policy_id") ?? "", severity: params.get("severity") ?? "",
    category: params.get("category") ?? "", scope: params.get("scope") || "current",
    sort: params.get("sort") || "priority", page: Number(params.get("page")) || 1,
  }
  const results = useQuery({
    queryKey: ["detection", "findings", listFilters], enabled: !invalid,
    queryFn: ({ signal }) => detection.findings(listFilters, signal),
  })
  const auditFilters = { platform: filters.platform, campaign_id: filters.campaign_id, policy_id: listFilters.policy_id, page: auditPage }
  const audit = useQuery({
    queryKey: ["detection", "suppressions", auditRun, auditFilters], enabled: auditRun !== null,
    queryFn: ({ signal }) => detection.suppressions(auditRun!, auditFilters, signal),
  })
  const run = useMutation({
    mutationFn: detection.run,
    onSuccess: async () => {
      await Promise.all([query.invalidateQueries({ queryKey: ["detection"] }), query.invalidateQueries({ queryKey: ["ai", "history"] })])
    },
  })
  const active = summary.data?.run

  function field(name: string, value: string) {
    change({ [name]: value, page: "" })
    setAuditPage(1)
  }

  function selectAudit(id: number) {
    setAuditPage(1)
    setAuditRun(id)
  }

  return <>
    <PageHeading title="Insights" description="Review evidence-backed performance risks, opportunities, and reporting issues.">
      <Button onClick={() => run.mutate()} disabled={run.isPending}>
        <Activity size={17} />{run.isPending ? "Running analysis…" : "Run Performance Analysis"}
      </Button>
    </PageHeading>
    {run.error && <ErrorPanel error={run.error} />}
    {run.data && <p className="support-text" role={run.data.status === "FAILED" ? "alert" : "status"}>
      {run.data.status === "FAILED" ? run.data.errors[0]?.message ?? "The detection run failed." :
        run.data.reused ? `Run #${run.data.id} already covers these inputs.` :
        `Run #${run.data.id} completed. ${run.data.campaign_count} campaigns evaluated.`}
    </p>}
    {summary.isError && <ErrorPanel error={summary.error} retry={() => void summary.refetch()} />}
    {active && <>
      <p className={active.state === "STALE" ? "coverage-note" : "report-period"}>
        {active.state === "STALE" && <CircleAlert size={17} />}
        Run #{active.id} · {active.state ? states[active.state] : active.status} · {dateRange(active.windows.current.start, active.windows.current.end)} · Completed {timestamp(active.finished_at)}
        {active.state === "STALE" && " · New performance data is available. Run analysis to refresh."}
      </p>
      <div className="insight-stats">
        {Object.entries(summaryLabels).map(([key, title]) => <Card key={key} className="metric-card">
          <h2>{title}</h2><p className="metric-value">{summary.data?.counts[key as keyof typeof summaryLabels] ?? 0}</p>
        </Card>)}
      </div>
    </>}
    <FilterBar filters={filters} setFilter={(key, value) => { setFilter(key, value); setAuditPage(1) }} invalid={invalid}
      campaigns={options.data ?? []} optionsUnavailable={options.isError}
      reset={() => {
        change({ start_date: "", end_date: "", platform: "", campaign_id: "", policy_id: "", severity: "", category: "", scope: "", sort: "", page: "" })
        setAuditPage(1)
      }} />
    <Card className="filter-card filter-bar" aria-label="Finding filters">
      <SelectField label="Policy" value={listFilters.policy_id} onChange={(value) => field("policy_id", value)}>
        <option value="">All policies</option>{Object.entries(policies).map(([value, label]) => <option key={value} value={value}>{value} · {label}</option>)}
      </SelectField>
      <SelectField label="Severity" value={listFilters.severity} onChange={(value) => field("severity", value)}>
        <option value="">All severities</option>{Object.entries(severities).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </SelectField>
      <SelectField label="Category" value={listFilters.category} onChange={(value) => field("category", value)}>
        <option value="">All categories</option>{Object.entries(categories).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </SelectField>
      <SelectField label="Run scope" value={listFilters.scope} onChange={(value) => field("scope", value)}>
        <option value="current">Latest evaluated period</option><option value="history">Historical runs</option><option value="all">All runs</option>
      </SelectField>
      <SelectField label="Sort findings" value={listFilters.sort} onChange={(value) => field("sort", value)}>
        <option value="priority">Priority</option><option value="newest">Newest evaluation</option><option value="spend">Spend exposure</option>
      </SelectField>
    </Card>
    {!invalid && (results.isPending ? <Loading label="Loading findings…" /> :
      results.isError ? <ErrorPanel error={results.error} retry={() => void results.refetch()} /> :
      results.data.total === 0 ? <Empty title="No findings for this selection" description={active ? "Adjust the filters or review run suppressions below." : "Run performance analysis to check the latest mature reporting period."} /> :
      <Card className="table-card">
        <PanelHeading title="Findings" description="Dates filter the run’s evaluation date. Evidence uses the reporting periods shown in each finding." />
        <FindingsTable findings={results.data.items} />
        <Pagination data={results.data} label="Finding pages" onChange={(page) => change({ page: String(page) })} />
      </Card>)}
    <Card className="table-card">
      <PanelHeading title="Detection run history" description="Open a run’s suppressions to see why an individual rule did not escalate." />
      {history.isPending ? <Loading label="Loading detection runs…" /> : history.isError ?
        <ErrorPanel error={history.error} retry={() => void history.refetch()} /> : history.data.total === 0 ?
        <p className="panel-empty">No runs recorded.</p> : <>
          <div className="table-scroll"><table className="data-table" aria-label="Detection runs">
            <thead><tr>{["Run", "Evaluation date", "Status", "Campaigns", "Findings", "Suppressed"].map((label) => <th key={label} scope="col">{label}</th>)}</tr></thead>
            <tbody>{history.data.items.map((item) => <RunRow key={item.id} run={item} open={auditRun === item.id} onClick={() => selectAudit(item.id)} />)}</tbody>
          </table></div>
          <Pagination data={history.data} label="Detection run pages" onChange={setHistoryPage} />
        </>}
    </Card>
    {auditRun !== null && <Card className="table-card">
      <PanelHeading title={`Suppressions for run #${auditRun}`} description="Platform, campaign, and policy filters apply to this audit.">
        <Button variant="ghost" onClick={() => setAuditRun(null)}>Close audit</Button>
      </PanelHeading>
      {audit.isPending ? <Loading label="Loading suppressions…" /> : audit.isError ?
        <ErrorPanel error={audit.error} retry={() => void audit.refetch()} /> : audit.data.total === 0 ?
        <p className="panel-empty">No suppressions match this selection.</p> : <>
          <ul className="quality-list">{audit.data.items.map((item) => <li key={item.id}>
            <strong>{item.campaign_name} · {item.policy_id} · {item.reason_code.toLowerCase().replaceAll("_", " ")}</strong>
            <p>{item.explanation}</p>
            <small>{item.evidence.current.observed_days} of {item.evidence.current.calendar_days} current days observed{item.evidence.baseline && ` · ${item.evidence.baseline.observed_days} of ${item.evidence.baseline.calendar_days} baseline days observed`}</small>
          </li>)}</ul>
          <Pagination data={audit.data} label="Suppression pages" onChange={setAuditPage} />
        </>}
    </Card>}
  </>
}

function timestamp(value: string) {
  return new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value))
}

function RunRow({ run, open, onClick }: { run: DetectionRun; open: boolean; onClick: () => void }) {
  return <tr>
    <th scope="row"><button type="button" className="text-link" aria-expanded={open} onClick={onClick}>Run #{run.id}</button>
      <small className="table-secondary">{timestamp(run.finished_at)}</small></th>
    <td>{dateLabel(run.evaluation_date, true)}</td><td>{run.status === "FAILED" ? "Failed" : run.state ? states[run.state] : "Completed"}</td>
    <td>{run.campaign_count}</td><td>{run.finding_count}</td><td>{run.suppression_count}</td>
  </tr>
}

export function FindingsTable({ findings }: { findings: Finding[] }) {
  return <div className="table-scroll" tabIndex={0} role="region" aria-label="Findings table">
    <table className="data-table" aria-label="Performance findings">
      <thead><tr>{["Finding", "Campaign", "Category", "Severity", "Evidence"].map((label) => <th key={label} scope="col">{label}</th>)}</tr></thead>
      <tbody>{findings.map((finding) => <tr key={finding.id}>
        <th scope="row"><Link className="text-link" to={`/insights/${finding.id}`}>{finding.summary}</Link>
          <small className="table-secondary">{finding.policy_id} · Run #{finding.run_id} · {states[finding.state]}</small></th>
        <td>{finding.campaign_snapshot.campaign_name}<small className="table-secondary finding-provenance">
          <PlatformBadge platform={finding.campaign_snapshot.platform} />
          {finding.current_evidence.fictional_days > 0 && <span>{finding.current_evidence.fictional_days === finding.current_evidence.observed_days ? "Fictional seed" : "Includes fictional data"}</span>}
        </small></td>
        <td>{categories[finding.category]}</td>
        <td><Badge className={`finding-severity finding-${finding.severity.toLowerCase()}`}>{severities[finding.severity]}</Badge></td>
        <td className="finding-key-evidence"><FindingMetric finding={finding} /></td>
      </tr>)}</tbody>
    </table>
  </div>
}

export function InsightDetail() {
  const id = useParams().findingId ?? ""
  const result = useQuery({ queryKey: ["detection", "finding", id], queryFn: ({ signal }) => detection.finding(id, signal) })
  const budgetLink = result.data && budgetFindingLink(result.data)
  return <>
    <Link to="/insights" className="text-link parent-link">Insights</Link>
    <PageHeading title={result.data?.summary ?? "Finding detail"} description={result.data ? `Detection run #${result.data.run_id}` : "Review the reporting evidence behind this finding."}>
      {result.data && <div className="budget-run-controls">
        <Link className="text-link" to={`/ai-analyst/${result.data.id}`}>Review in AI Analyst</Link>
        <Link className="text-link" to={`/strategy-briefs/new?finding_id=${result.data.id}`}>Include in Strategy Brief</Link>
        {budgetLink && <Link className="text-link" to={budgetLink}>Model a budget scenario</Link>}
      </div>}
    </PageHeading>
    {result.isPending ? <Loading label="Loading finding evidence…" /> :
      result.isError ? <ErrorPanel error={result.error} retry={() => void result.refetch()} /> :
      <FindingEvidence finding={result.data} />}
  </>
}
