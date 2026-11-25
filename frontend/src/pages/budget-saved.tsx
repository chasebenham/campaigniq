import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link, useNavigate } from "react-router"

import { BudgetResults, OutcomeCells, money } from "@/components/budget-results"
import { SelectField } from "@/components/filters"
import { ErrorPanel, Loading, Pagination, PanelHeading } from "@/components/shared"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { budgetApi, cases, caseNames, type SavedScenario } from "@/lib/budget"
import { dateLabel, dateRange } from "@/lib/presentation"

function Status({ status }: { status: SavedScenario["status"] }) {
  return <span className={status === "STALE" ? "budget-blocked" : "support-text"}>
    {status === "STALE" ? "Source data changed" : "Reference data current"}
  </span>
}

export function BudgetHistory() {
  const [page, setPage] = useState(1)
  const history = useQuery({
    queryKey: ["budget", "scenarios", page], queryFn: ({ signal }) => budgetApi.scenarios(page, signal),
  })
  return <Card className="table-card">
    <PanelHeading title="Saved scenarios" description="Open a snapshot, duplicate its assumptions, or compare saved alternatives." />
    {history.isPending ? <Loading label="Loading saved scenarios…" /> : history.isError ?
      <ErrorPanel error={history.error} retry={() => void history.refetch()} /> :
      history.data.items.length === 0 ? <p className="budget-panel-body support-text">No scenarios on this page.</p> : <>
        <div className="table-scroll"><table className="data-table" aria-label="Saved scenarios">
          <thead><tr>{["Scenario", "Planning dates", "Total budget", "Saved", "Evidence"].map(label => <th scope="col" key={label}>{label}</th>)}</tr></thead>
          <tbody>{history.data.items.map(row => <tr key={row.id}>
            <th scope="row"><Link className="text-link" to={`/budget-lab/${row.id}`}>{row.name}</Link></th>
            <td>{dateRange(row.planning.start, row.planning.end)}</td><td>{money(row.total_budget)}</td>
            <td>{dateLabel(row.created_at, true)}</td><td><Status status={row.status} /></td>
          </tr>)}</tbody>
        </table></div>
        <Pagination data={history.data} onChange={setPage} label="Saved scenario pages" />
      </>}
  </Card>
}

export function BudgetSavedView({ id }: { id: string }) {
  const cache = useQueryClient()
  const navigate = useNavigate()
  const [compareId, setCompareId] = useState("")
  const [comparisonPage, setComparisonPage] = useState(1)
  const saved = useQuery({ queryKey: ["budget", "scenario", id], queryFn: ({ signal }) => budgetApi.scenario(id, signal) })
  const alternatives = useQuery({
    queryKey: ["budget", "scenarios", comparisonPage], queryFn: ({ signal }) => budgetApi.scenarios(comparisonPage, signal),
  })
  const comparison = useQuery({
    queryKey: ["budget", "scenario", compareId], enabled: Boolean(compareId),
    queryFn: ({ signal }) => budgetApi.scenario(compareId, signal),
  })
  const clone = useMutation({
    mutationFn: budgetApi.clone,
    onSuccess: (scenario) => {
      cache.setQueryData(["budget", "scenario", String(scenario.id)], scenario)
      void cache.invalidateQueries({ queryKey: ["budget", "scenarios"] })
      navigate(`/budget-lab/${scenario.id}`)
    },
  })
  if (saved.isPending) return <Loading label="Loading saved result…" />
  if (saved.isError) return <ErrorPanel error={saved.error} retry={() => void saved.refetch()} />
  const row = saved.data
  return <>
    <Card>
      <PanelHeading title={row.name} description={`Saved ${dateLabel(row.created_at, true)} · Model ${row.model_version}`}>
        <div className="budget-run-controls">
          <Link className="text-link" to={`/budget-lab?draft=${row.id}`}>Use as draft</Link>
          <Button variant="outline" disabled={clone.isPending} onClick={() => clone.mutate(row.id)}>
            {clone.isPending ? "Cloning…" : "Clone scenario"}
          </Button>
        </div>
      </PanelHeading>
      <div className="budget-panel-body budget-snapshot-meta">
        <Status status={row.status} />
        {row.status === "STALE" && <p>These saved assumptions and results are preserved. Use as draft to model with the latest evidence.</p>}
        {row.cloned_from_id && <Link className="text-link" to={`/budget-lab/${row.cloned_from_id}`}>View source scenario</Link>}
        {row.plan.finding_id && <Link className="text-link" to={`/insights/${row.plan.finding_id}`}>View linked finding</Link>}
        <Link className="text-link" to={`/strategy-briefs/new?budget_id=${row.id}`}>Use in Strategy Brief</Link>
      </div>
      {clone.error && <ErrorPanel error={clone.error} />}
    </Card>
    <Card className="table-card">
      <PanelHeading title="Compare alternatives" description="Compare saved portfolio results using each plan’s own dates, assumptions, and evidence." />
      <div className="budget-panel-body filter-bar">
        <SelectField label="Compare with" value={compareId} onChange={setCompareId} disabled={alternatives.isPending || alternatives.isError}>
          <option value="">Select a saved scenario</option>
          {compareId && !alternatives.data?.items.some(item => String(item.id) === compareId) &&
            <option value={compareId}>{comparison.data?.name ?? `Scenario #${compareId}`}</option>}
          {alternatives.data?.items.filter(item => item.id !== row.id).map(item =>
            <option key={item.id} value={item.id}>{item.name}</option>)}
        </SelectField>
      </div>
      {alternatives.data && <Pagination data={alternatives.data} onChange={setComparisonPage} label="Comparison scenario pages" />}
      {alternatives.isError && <ErrorPanel error={alternatives.error} retry={() => void alternatives.refetch()} />}
      {compareId && (comparison.isPending ? <Loading label="Loading comparison…" /> :
        comparison.isError ? <ErrorPanel error={comparison.error} retry={() => void comparison.refetch()} /> :
        <ScenarioComparison left={row} right={comparison.data} />)}
    </Card>
    <BudgetResults result={row.result} plan={row.plan} frozen />
  </>
}

function ScenarioComparison({ left, right }: { left: SavedScenario; right: SavedScenario }) {
  const different = [
    left.evidence_fingerprint !== right.evidence_fingerprint && "reference evidence",
    left.planning.start !== right.planning.start || left.planning.end !== right.planning.end ? "planning dates" : "",
    left.model_version !== right.model_version && "model versions",
  ].filter(Boolean).join(", ")
  return <>
    {different && <p className="budget-panel-body support-text">These snapshots use different {different}. Interpret the results in context.</p>}
    <div className="table-scroll" role="region" aria-label="Saved scenario comparison" tabIndex={0}>
      <table className="data-table">
        <thead><tr>{["Saved scenario", "Case", "Spend", "Attributed purchase credit", "Attributed value", "CPA", "ROAS"].map(label =>
          <th scope="col" key={label}>{label}</th>)}</tr></thead>
        <tbody>{cases.flatMap(name => [left, right].map(row => <tr key={`${row.id}-${name}`}>
          <th scope="row">{row.name}{row.status === "STALE" && <small className="table-secondary budget-blocked">Source data changed</small>}</th>
          <td>{caseNames[name]}</td><OutcomeCells data={row.result.scenarios[name].portfolio} />
        </tr>))}</tbody>
      </table>
    </div>
  </>
}
