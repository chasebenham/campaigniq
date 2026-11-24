import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Info, Sparkles } from "lucide-react"
import { Link, useNavigate, useParams } from "react-router"

import { SelectField } from "@/components/filters"
import { FindingBadges, FindingEvidence, FindingMetric, evidenceLabel, evidenceValue } from "@/components/finding-evidence"
import { Empty, ErrorPanel, Loading, PageHeading, Pagination, PanelHeading } from "@/components/shared"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { actionLabels, ai, unavailableMessages, type Analysis } from "@/lib/ai"
import type { Decimal, MetricKey, Page } from "@/lib/api"
import { detection } from "@/lib/detection"
import { dateRange, formatMetric, metricNames } from "@/lib/presentation"

export function AiAnalyst() {
  const id = useParams().findingId ?? ""
  const navigate = useNavigate()
  const cache = useQueryClient()
  const [scope, setScope] = useState("current")
  const [optionPage, setOptionPage] = useState(1)
  const [historyPage, setHistoryPage] = useState(1)
  const [selectedAnalysis, setSelectedAnalysis] = useState<number | null>(null)
  const available = useQuery({ queryKey: ["ai", "availability"], staleTime: 0, queryFn: ({ signal }) => ai.availability(signal) })
  const check = useMutation({ mutationFn: ai.check, onSuccess: (result) => cache.setQueryData(["ai", "availability"], result) })
  const options = useQuery({
    queryKey: ["detection", "ai-options", scope, optionPage],
    queryFn: ({ signal }) => detection.findings({ scope, page: optionPage, page_size: 15 }, signal),
  })
  const finding = useQuery({
    queryKey: ["detection", "finding", id], enabled: Boolean(id), queryFn: ({ signal }) => detection.finding(id, signal),
  })
  const history = useQuery({
    queryKey: ["ai", "history", id, historyPage], enabled: Boolean(id) && finding.isSuccess,
    queryFn: ({ signal }) => ai.history(id, historyPage, signal),
    refetchInterval: (query) => query.state.data?.items.some((item) => item.status === "PENDING") ? 1_500 : false,
  })
  const run = useMutation({
    mutationFn: ai.analyze,
    onSuccess: () => { setSelectedAnalysis(null); setHistoryPage(1) },
    onSettled: async (_output, _error, { id: findingId }) => {
      await Promise.all([
        cache.invalidateQueries({ queryKey: ["ai", "history", findingId] }),
        cache.invalidateQueries({ queryKey: ["detection", "finding", findingId] }),
        cache.invalidateQueries({ queryKey: ["ai", "availability"] }),
      ])
    },
  })
  const current = finding.data
  const fromThisFinding = run.variables?.id === id
  const latestHistory = historyPage === 1 ? history.data : cache.getQueryData<Page<Analysis>>(["ai", "history", id, 1])
  const pending = (fromThisFinding && run.isPending) || (latestHistory?.items.some((item) => item.status === "PENDING") ?? false)
  const completed = latestHistory?.items.find((item) => item.is_current)
  const historyRows = history.data?.items ?? []
  const selected = historyRows.find((item) => item.id === selectedAnalysis)
    ?? historyRows.find((item) => item.is_current) ?? historyRows[0]
  const canAnalyze = Boolean(available.data?.enabled && current?.state === "CURRENT" && !pending && !history.isPending && !history.isError)

  function chooseFinding(value: string) {
    setHistoryPage(1)
    setSelectedAnalysis(null)
    navigate(value ? `/ai-analyst/${value}` : "/ai-analyst")
  }

  return <>
    <PageHeading title="AI Analyst" description="Request a marketing interpretation of a verified performance finding.">
      {available.data?.enabled && <Button variant="outline" disabled={check.isPending} onClick={() => check.mutate()}>
        {check.isPending ? "Checking connection…" : "Check OpenAI connection"}
      </Button>}
    </PageHeading>
    {available.isError && <ErrorPanel error={available.error} retry={() => void available.refetch()} />}
    {check.error && <ErrorPanel error={check.error} />}
    {available.data?.enabled && available.data.model && <p className="support-text" role="status">
      {available.data.model} · {available.data.provider_status === "ACCESSIBLE" ? "Provider access verified" :
        available.data.provider_status === "ERROR" ? "Provider error" : "Configured"}
    </p>}
    {available.data?.reason && <aside className="attribution-notice">
      <Info size={18} aria-hidden="true" /><div><strong>{unavailableMessages[available.data.reason]}</strong>
        <p>{available.data.provider_message ?? "You can review verified evidence and previous analyses."}</p></div>
    </aside>}
    <Card className="evidence-card">
      <PanelHeading title="Select a finding" description="Choose a deterministic finding from Insights." />
      <div className="filter-bar ai-selection">
        <SelectField label="Finding scope" value={scope} onChange={(value) => { setScope(value); setOptionPage(1) }}>
          <option value="current">Latest evaluated period</option><option value="all">All detection runs</option>
        </SelectField>
        <SelectField label="Finding" value={id} onChange={chooseFinding} disabled={options.isError && !current}>
          <option value="">Choose a finding</option>
          {id && !options.data?.items.some((item) => String(item.id) === id) && <option value={id}>
            {current ? `${current.campaign_snapshot.campaign_name} · ${current.summary}` : `Finding #${id}`}
          </option>}
          {options.data?.items.map((item) => <option key={item.id} value={item.id}>
            {item.campaign_snapshot.campaign_name} · {item.summary}
          </option>)}
        </SelectField>
      </div>
      {options.data && <Pagination data={options.data} onChange={setOptionPage} label="Available finding pages" />}
      {options.isError && <ErrorPanel error={options.error} retry={() => void options.refetch()} />}
    </Card>
    {!id ? <Empty title="Choose a verified finding" description={options.data?.total === 0
      ? "Run performance analysis in Insights to check for eligible campaign findings."
      : "Review a finding’s measurements before asking for an interpretation."} /> :
      finding.isPending ? <Loading label="Loading verified finding…" /> :
      finding.isError ? <ErrorPanel error={finding.error} retry={() => void finding.refetch()} /> : current && <>
        <Card className="evidence-card">
          <PanelHeading title={current.summary} description={current.campaign_snapshot.campaign_name}>
            <FindingBadges finding={current} />
          </PanelHeading>
          <div className="finding-meta">
            <strong><FindingMetric finding={current} /></strong>
            <span>{dateRange(current.current_evidence.start, current.current_evidence.end)}</span>
            {current.current_evidence.fictional_days > 0 && <span>{current.current_evidence.fictional_days === current.current_evidence.observed_days ? "Fictional seed evidence" : "Includes fictional data"}</span>}
            <Link className="text-link" to={`/insights/${current.id}`}>Open finding in Insights</Link>
          </div>
          <div className="analyst-controls">
            <Button disabled={!canAnalyze || Boolean(completed)} onClick={() => run.mutate({ id })}>
              <Sparkles size={17} />{pending ? "Analyzing…" : "Analyze with AI"}
            </Button>
            {completed && <Button variant="outline" disabled={!canAnalyze} onClick={() => run.mutate({
              id, regeneration: { regenerate_from: completed.id, request_id: crypto.randomUUID() },
            })}>Regenerate analysis</Button>}
            {current.state !== "CURRENT" ? <span>Choose a current finding to generate a new analysis.</span> :
              completed ? <span>Regenerating requests a new analysis and preserves earlier versions.</span> : null}
          </div>
          {pending && <p role="status" className="evidence-body">Generating an interpretation from verified evidence…</p>}
          {fromThisFinding && run.error && <div className="import-error" role="alert">{run.error.message}</div>}
        </Card>
        <details className="evidence-disclosure">
          <summary>Review verified metrics and rule evidence</summary>
          <div><FindingEvidence finding={current} /></div>
        </details>
        {history.isPending ? <Loading label="Loading analysis history…" /> :
          history.isError ? <ErrorPanel error={history.error} retry={() => void history.refetch()} /> :
          historyRows.length === 0 ? <Empty title="No AI analyses for this finding" description="A requested analysis will appear here with its evidence references." /> : <>
            <Card className="evidence-card">
              <PanelHeading title="Analysis history" description="Previous attempts and completed interpretations for this finding." />
              <div className="ai-selection"><SelectField label="Analysis version" value={selected ? String(selected.id) : ""}
                onChange={(value) => setSelectedAnalysis(Number(value))}>
                {historyRows.map((item) => <option key={item.id} value={item.id}>
                  #{item.id} · {analysisLabel(item)} · {new Date(item.created_at).toLocaleString("en-US")}
                </option>)}
              </SelectField></div>
              <Pagination data={history.data} onChange={(page) => { setHistoryPage(page); setSelectedAnalysis(null) }} label="Analysis history pages" />
            </Card>
            {selected && <AnalysisResult analysis={selected} />}
          </>}
      </>}
  </>
}

function analysisLabel(analysis: Analysis) {
  if (analysis.status === "COMPLETED") return analysis.is_current ? "Current analysis" : "Previous analysis"
  return { PENDING: "In progress", STALE: "Stale evidence", FAILED: "Failed" }[analysis.status]
}

function TextList({ items }: { items: string[] }) {
  return items.length ? <ul className="analysis-list">{items.map((item, index) => <li key={index}>{item}</li>)}</ul> :
    <p className="evidence-body">No items were returned.</p>
}

function AnalysisResult({ analysis }: { analysis: Analysis }) {
  const output = analysis.structured_output
  if (!output) return analysis.status === "PENDING" ? null :
    <Card className="evidence-card"><PanelHeading title="Analysis attempt" description={analysis.error_message ?? "This attempt returned no interpretation."} /></Card>

  const experiment = output.proposed_experiment
  return <>
    <Card className="evidence-card analyst-result">
      <PanelHeading title="AI-generated interpretation" description={`Analysis #${analysis.id} · ${analysis.model} · Prompt ${analysis.prompt_version} · Schema ${analysis.schema_version}`}>
        <Badge className="fictional-badge">{analysisLabel(analysis)}</Badge>
      </PanelHeading>
      {!analysis.is_current && <p className="evidence-body">{analysis.status === "STALE"
        ? "Evidence changed during this request. Review the current finding before using this interpretation."
        : "This is a previous analysis version. Its original evidence references remain available."}</p>}
      <div className="analyst-copy">
        <div><h3>Executive summary</h3><p>{output.executive_summary}</p></div>
        <div><h3>Potential business impact</h3><p>{output.business_impact_assessment}</p></div>
        <div><h3>Suggested next step · {actionLabels[output.recommended_action_type]}</h3><p>{output.recommended_action}</p>
          {output.action_rationale && <p className="mt-2">{output.action_rationale}</p>}</div>
        <div><h3>Basis for confidence</h3><p>{output.confidence_rationale}</p></div>
      </div>
    </Card>
    <div className="evidence-grid">
      <Card className="evidence-card"><PanelHeading title="Diagnostic hypotheses" description="Possible explanations to investigate." />
        <TextList items={output.possible_explanations} /></Card>
      <Card className="evidence-card"><PanelHeading title="Missing information" />
        <TextList items={output.missing_information} /></Card>
    </div>
    {experiment && <Card className="evidence-card experiment-card">
      <PanelHeading title="Proposed experiment" description={output.experiment_hypothesis ?? undefined} />
      <dl className="evidence-values">{Object.entries({
        "Proposed change": experiment.proposed_change, "Control or comparator": experiment.comparison,
        Design: experiment.design, Scope: experiment.audience_or_scope, "Measurement window": experiment.duration,
        Guardrails: experiment.guardrails, "Guardrail metrics": experiment.guardrail_metrics?.join(", "),
        "Decision rule": experiment.decision_rule,
        "Primary success metric": output.primary_success_metric,
        "Secondary metrics": output.secondary_metrics.length ? output.secondary_metrics.join(", ") : null,
      }).filter(([, value]) => value).map(([title, value]) => <div key={title}><dt>{title}</dt><dd>{value}</dd></div>)}</dl>
    </Card>}
    <div className="evidence-grid">
      <Card className="evidence-card"><PanelHeading title="Evidence references" description="Values from the saved evidence snapshot." />
        <dl className="evidence-values">{analysis.evidence_references.map(({ path, value }) => <Reference key={path} path={path} value={value}
          claim={output.numeric_claims?.find((item) => item.reference === path)?.value} />)}</dl>
      </Card>
      <Card className="evidence-card"><PanelHeading title="Risks and limitations" /><TextList items={output.risks_and_limitations} /></Card>
    </div>
  </>
}

function Reference({ path, value, claim }: { path: string; value: string | number | boolean; claim?: string }) {
  const parts = path.split(".")
  const key = parts.at(-1) ?? path
  const isMetric = parts[1] === "metrics" && Object.hasOwn(metricNames, key)
  const targetMetric = path === "targets.target_cpa" ? "cpa" : path === "targets.target_roas" ? "roas" : null
  const metric = isMetric ? key as MetricKey : targetMetric
  const title = isMetric
    ? `${parts[0] === "current" ? "Current" : "Baseline"} · ${metricNames[key as MetricKey]}`
    : targetMetric ? `Target ${metricNames[targetMetric]}` : `${evidenceLabel(parts[0])} · ${evidenceLabel(key)}`
  const formatted = metric && typeof value !== "boolean" ? formatMetric(metric, value as Decimal | number)
    : evidenceValue(key, value)
  return <div><dt>{title}<code className="table-secondary">{path}</code></dt><dd>{formatted}
    {claim && <small className="table-secondary">Verified AI citation {claim}</small>}
  </dd></div>
}
