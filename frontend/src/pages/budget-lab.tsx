import { useState, type InputHTMLAttributes } from "react"
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query"
import { CircleAlert, Info } from "lucide-react"
import { Link, useNavigate, useParams, useSearchParams } from "react-router"

import { BenchmarkNotes, BudgetResults, HistoricalTable } from "@/components/budget-results"
import { SelectField } from "@/components/filters"
import { ActionRequirements, Empty, ErrorPanel, Loading, PageHeading, Pagination, PanelHeading, PlatformBadge } from "@/components/shared"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { ApiError } from "@/lib/api"
import {
  budgetApi, cases, caseNames, unitInput, units, type Assumptions, type Benchmark,
  type BudgetCase, type CaseAssumption, type Defaults, type Mode, type Plan, type Selection,
} from "@/lib/budget"
import type { Window } from "@/lib/detection"
import { dateLabel, platformNames } from "@/lib/presentation"
import { BudgetHistory, BudgetSavedView } from "./budget-saved"

const emptyPeriod = { start: "", end: "" }
const maxCents = 10_000_000_000

const assumptionFields: { key: keyof CaseAssumption; label: string; min: number; max: number; help: string }[] = [
  { key: "cpa_change_pct", label: "Base CPA change (%)", min: -90, max: 300, help: "Change from the observed attributed CPA." },
  { key: "marginal_cpa_change_pct", label: "Extra CPA above history (%)", min: 0, max: 300, help: "Additional CPA change on spend above the normalized baseline." },
  { key: "value_per_purchase_change_pct", label: "Attributed value per purchase change (%)", min: -95, max: 300, help: "Change from observed attributed value per purchase." },
]

function validDateRange(range: Window) {
  const days = (Date.parse(range.end) - Date.parse(range.start)) / 86_400_000
  return days >= 0 && days < 90
}

function assumptionIssues(assumptions: Assumptions) {
  return cases.flatMap(name => assumptionFields.flatMap(({ key, min, max, label }) => {
    const input = assumptions[name][key]
    const valid = /^-?\d{1,3}(?:\.\d{0,2})?$/.test(input) && Number(input) >= min && Number(input) <= max
    return valid ? [] : [`In the ${caseNames[name]} case, enter a value from ${min}% to ${max}% for ${label.replace(" (%)", "")}, with up to two decimal places.`]
  }))
}

function positiveId(value: string | null) {
  return value && /^\d{1,10}$/.test(value) && Number(value) > 0 && Number(value) <= 2_147_483_647 ? Number(value) : undefined
}

function Field({ label, help, ...props }: { label: string; help?: string } & InputHTMLAttributes<HTMLInputElement>) {
  return <label className="filter-field"><span>{label}</span><input {...props} />{help && <small className="support-text">{help}</small>}</label>
}

function Notice({ id, children }: { id?: string; children: string }) {
  return <p id={id} className="budget-input-notice" role="alert"><CircleAlert size={16} aria-hidden="true" />{children}</p>
}

export function BudgetLab() {
  const { scenarioId } = useParams()
  const [search] = useSearchParams()
  const sourceId = positiveId(search.get("draft"))
  const campaignId = positiveId(search.get("campaign_id"))
  const findingId = campaignId ? positiveId(search.get("finding_id")) : undefined
  const initial = useQuery({ queryKey: ["budget", "defaults"], enabled: !scenarioId, queryFn: ({ signal }) => budgetApi.defaults(signal) })
  const copy = useQuery({
    queryKey: ["budget", "scenario", String(sourceId)],
    enabled: !scenarioId && Boolean(sourceId), queryFn: ({ signal }) => budgetApi.scenario(String(sourceId), signal),
  })
  return <>
    <PageHeading title="Budget Lab" description="Compare paid-media allocations against observed performance.">
      {scenarioId && <Link className="text-link" to="/budget-lab">New scenario</Link>}
    </PageHeading>
    <aside className="attribution-notice">
      <Info size={18} aria-hidden="true" /><div><strong>Hypothetical planning scenarios</strong>
        <p>Modeled results use platform-attributed purchase credit and value. Customer overlap, profitability, and incremental returns require separate evidence.</p></div>
    </aside>
    {scenarioId ? <BudgetSavedView key={scenarioId} id={scenarioId} /> :
      initial.isError ? <ErrorPanel error={initial.error} retry={() => void initial.refetch()} /> :
      copy.isError ? <ErrorPanel error={copy.error} retry={() => void copy.refetch()} /> :
      initial.isPending || (sourceId && copy.isPending) ? <Loading label="Loading planning settings…" /> :
      <BudgetDraft key={search.toString()} settings={initial.data} source={sourceId ? copy.data?.plan : undefined}
        campaignId={campaignId} findingId={findingId} />}
    <BudgetHistory />
  </>
}

function BudgetDraft({ settings, source, campaignId, findingId }: {
  settings: Defaults; source?: Plan; campaignId?: number; findingId?: number;
}) {
  const navigate = useNavigate()
  const cache = useQueryClient()
  const [name, setName] = useState(source ? `${source.name.slice(0, 92).trimEnd()} (draft)` : "New scenario")
  const [reference, setReference] = useState(source?.reference ?? settings.reference ?? emptyPeriod)
  const [planning, setPlanning] = useState(source?.planning ?? settings.planning)
  const [total, setTotal] = useState(source?.total_budget ?? "")
  const [mode, setMode] = useState<Mode>(source?.mode ?? "DOLLARS")
  const [ids, setIds] = useState(source?.campaign_ids ?? (campaignId ? [campaignId] : []))
  const [values, setValues] = useState<Record<number, string>>(Object.fromEntries(source?.allocations.map(row => [row.campaign_id, row.value]) ?? []))
  const [assumptions, setAssumptions] = useState(source?.assumptions ?? settings.assumptions)
  const [active, setActive] = useState<BudgetCase>("base")
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState("")
  const [platform, setPlatform] = useState("")
  const [notice, setNotice] = useState("")
  const [linkedFinding, setLinkedFinding] = useState(findingId ?? source?.finding_id)

  const referenceIssue = !reference.start || !reference.end ? "Enter both reference dates." :
    !validDateRange(reference) ? "Choose a reference period of 1 to 90 days, with the start on or before the end." :
    reference.end > settings.mature_through ? `Choose a reference end on or before ${dateLabel(settings.mature_through, true)} so conversions have time to mature.` : ""
  const planningIssue = !planning.start || !planning.end ? "Enter both planning dates." :
    !validDateRange(planning) ? "Choose a planning period of 1 to 90 days, with the start on or before the end." :
    planning.start < settings.earliest_planning_date ? `Start planning on or after ${dateLabel(settings.earliest_planning_date, true)} (UTC).` :
    reference.end && planning.start <= reference.end ? "Start the planning period after the reference period ends." : ""
  const referenceValid = !referenceIssue
  const queryParams = { start_date: reference.start, end_date: reference.end }
  const options = useQuery({
    queryKey: ["budget", "benchmarks", reference, platform, search, page],
    enabled: referenceValid, queryFn: ({ signal }) => budgetApi.benchmarks({ ...queryParams, q: search.trim(), platform, page }, signal),
  })
  const selectedQueries = useQueries({
    queries: ids.map(id => ({
      queryKey: ["budget", "benchmark", reference, id],
      enabled: referenceValid && !options.data?.items.some(row => row.campaign_id === id),
      queryFn: ({ signal }: { signal: AbortSignal }) => budgetApi.benchmarks({ ...queryParams, campaign_id: id }, signal),
    })),
  })
  const selected = ids.map((id, index) => options.data?.items.find(row => row.campaign_id === id) ?? selectedQueries[index]?.data?.items[0])
  const rows = selected.filter((row): row is Benchmark => Boolean(row))
  const eligible = rows.filter(row => row.eligible)
  const selectedLoading = referenceValid && ids.some((_, index) => !selected[index] && selectedQueries[index]?.isFetching)
  const selectedError = referenceValid && selectedQueries.find((query, index) => !selected[index] && query.isError)?.error
  const missingSelection = referenceValid && !selectedLoading && !selectedError && rows.length < ids.length
  const linked = ids.length ? linkedFinding : undefined

  const budgetUnits = units(total)
  const budgetIssue = !total.trim() ? "Enter a total budget in USD." :
    budgetUnits == null || budgetUnits > maxCents ? "Enter a USD amount from 0 to 100,000,000 with up to two decimal places (for example, 1000.00)." : ""
  const target = mode === "PERCENT" ? 10_000 : budgetUnits
  const entered = ids.map(id => units(values[id] ?? "0"))
  const sum = entered.reduce<number>((subtotal, value) => subtotal + (value ?? 0), 0)
  const remaining = target == null || entered.some(value => value == null) ? null : target - sum
  const blockedAllocations = rows.filter(row => !row.eligible && units(values[row.campaign_id] ?? "0") !== 0)
  const validAmounts = remaining === 0 && !blockedAllocations.length
  const campaignIssue = selectedLoading ? "Wait for the selected campaign benchmarks to load." :
    selectedError ? "Retry loading the selected campaign benchmarks or remove the unavailable campaigns." :
    missingSelection ? "Remove unavailable campaigns from the selection." :
    eligible.length < 2 && referenceValid ? `Select at least two eligible campaigns for these reference dates (${eligible.length} selected and eligible).` : ""
  const prerequisites = [referenceIssue, planningIssue, budgetIssue, campaignIssue].filter(Boolean)
  const canAllocate = !prerequisites.length
  const invalidAllocations = rows.filter(row => row.eligible && units(values[row.campaign_id] ?? "0") == null)
  const allocationBalance = remaining == null || remaining === 0 || budgetIssue || eligible.length < 2 ? "" :
    mode === "PERCENT" ? `Percentage allocations must add up to 100%. ${remaining > 0 ? "Allocate" : "Remove"} ${unitInput(Math.abs(remaining))} percentage points.` :
    `Dollar allocations must match the total budget. ${remaining > 0 ? "Allocate" : "Remove"} $${unitInput(Math.abs(remaining))}.`
  const assumptionsToFix = assumptionIssues(assumptions)
  const requirements = [
    ...(!name.trim() ? ["Enter a scenario name."] : []), ...prerequisites,
    ...invalidAllocations.map(row => `Enter a nonnegative allocation for ${row.campaign_name} with up to two decimal places.`),
    ...blockedAllocations.map(row => `Set the allocation for ${row.campaign_name} to zero because it is blocked for these reference dates.`),
    allocationBalance, ...assumptionsToFix,
  ].filter(Boolean)
  const selection: Selection = { reference, planning, total_budget: total, campaign_ids: ids }
  const allocations = ids.map(id => ({ campaign_id: id, value: values[id] ?? "0" }))
  const plan: Plan = { ...selection, name, mode, allocations, assumptions, finding_id: linked }
  const validPlan = canAllocate && validAmounts && !requirements.length

  const calculate = useMutation({ mutationFn: budgetApi.calculate })
  const current = calculate.data && JSON.stringify(calculate.variables) === JSON.stringify(plan) ? calculate.data : undefined
  const preset = useMutation({
    mutationFn: budgetApi.allocations,
    onSuccess: (items, mutation) => {
      const next: Mode = mutation.method === "convert" ? mutation.mode === "DOLLARS" ? "PERCENT" : "DOLLARS" : mode
      setMode(next)
      setValues(Object.fromEntries(items.map(row => [row.campaign_id, next === "DOLLARS" ? row.dollars : row.percent])))
      setNotice("")
    },
  })
  const save = useMutation({
    mutationFn: (hash: string) => budgetApi.save(plan, hash),
    onError: error => {
      if (error instanceof ApiError && error.code === "STALE_BENCHMARK") calculate.reset()
    },
    onSuccess: (scenario) => {
      cache.setQueryData(["budget", "scenario", String(scenario.id)], scenario)
      void cache.invalidateQueries({ queryKey: ["budget", "scenarios"] })
      navigate(`/budget-lab/${scenario.id}`)
    },
  })

  function choose(id: number) {
    setNotice("")
    if (ids.includes(id)) {
      if (linked && (id === campaignId || !campaignId)) setLinkedFinding(undefined)
      setIds(ids.filter(key => key !== id))
      setValues(Object.fromEntries(Object.entries(values).filter(([key]) => Number(key) !== id)))
    } else if (ids.length < settings.max_campaigns) setIds([...ids, id])
  }

  function changeMode(next: string) {
    const nextMode = next === "DOLLARS" ? "DOLLARS" : "PERCENT"
    if (nextMode === mode) return
    if (entered.every(value => value === 0) && (sum !== target || budgetUnits === 0)) {
      setMode(nextMode)
      setNotice("")
    } else if (canAllocate && validAmounts) {
      setNotice("")
      preset.mutate({ ...selection, method: "convert", mode, allocations })
    } else {
      setNotice("Balance the current allocation before switching units.")
    }
  }

  function balance() {
    const last = eligible.at(-1)
    if (!last || remaining == null) return
    const key = last.campaign_id
    const updated = (units(values[key] ?? "0") ?? 0) + remaining
    if (updated < 0) {
      setNotice("This campaign cannot absorb the excess allocation. Reduce one or more entries first.")
      return
    }
    setNotice("")
    setValues({ ...values, [key]: unitInput(updated) })
  }

  return <>
    <fieldset className="budget-draft" disabled={preset.isPending || save.isPending}>
      <Card>
        <PanelHeading title="Scenario controls"
          description={`Reference dates through ${dateLabel(settings.mature_through, true)} allow ${settings.maturation_days} full days for conversion maturation.`} />
        <div className="budget-panel-body budget-controls">
          <Field label="Scenario name" required value={name} maxLength={100} onChange={event => setName(event.currentTarget.value)} />
          <Field label="Total budget (USD)" required inputMode="decimal" value={total} placeholder="0.00" maxLength={12}
            onChange={event => setTotal(event.currentTarget.value)} />
          <Field label="Reference start" required type="date" value={reference.start} max={settings.mature_through}
            onChange={event => { setReference({ ...reference, start: event.currentTarget.value }); setPage(1) }} />
          <Field label="Reference end" required type="date" value={reference.end} max={settings.mature_through}
            onChange={event => { setReference({ ...reference, end: event.currentTarget.value }); setPage(1) }} />
          <Field label="Planning start" required type="date" value={planning.start} min={settings.earliest_planning_date}
            onChange={event => setPlanning({ ...planning, start: event.currentTarget.value })} />
          <Field label="Planning end" required type="date" value={planning.end} min={planning.start || settings.earliest_planning_date}
            onChange={event => setPlanning({ ...planning, end: event.currentTarget.value })} />
        </div>
        {linked && <p className="budget-panel-body support-text">Linked evidence · <Link className="text-link" to={`/insights/${linked}`}>Finding #{linked}</Link></p>}
        {(referenceIssue || planningIssue || (total && budgetIssue)) && <div className="budget-panel-body">
          {referenceIssue && <Notice>{referenceIssue}</Notice>}
          {planningIssue && <Notice>{planningIssue}</Notice>}
          {total && budgetIssue && <Notice>{budgetIssue}</Notice>}
        </div>}
      </Card>
      <Card className="table-card">
        <PanelHeading title="Choose campaigns" description={`${ids.length} selected · ${eligible.length} eligible · ${settings.minimum_observed_days} mature campaign-days required`} />
        <div className="budget-panel-body filter-bar">
          <Field label="Find a campaign" type="search" value={search} maxLength={80} placeholder="Search by name"
            onChange={event => { setSearch(event.currentTarget.value); setPage(1) }} />
          <SelectField label="Platform" value={platform} onChange={value => { setPlatform(value); setPage(1) }}>
            <option value="">All platforms</option>
            {Object.entries(platformNames).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </SelectField>
        </div>
        {referenceValid && (options.isPending ? <Loading label="Loading historical campaigns…" /> :
          options.isError ? <ErrorPanel error={options.error} retry={() => void options.refetch()} /> :
          options.data.items.length === 0 ? <p className="budget-panel-body support-text">No campaigns match these filters.</p> :
          <div className="budget-panel-body">
            <div className="budget-campaign-grid">{options.data.items.map(row => <label className="budget-campaign-option" key={row.campaign_id}>
              <input type="checkbox" checked={ids.includes(row.campaign_id)} disabled={ids.length >= settings.max_campaigns && !ids.includes(row.campaign_id)}
                onChange={() => choose(row.campaign_id)} />
              <span><strong>{row.campaign_name}</strong><small>{platformNames[row.platform]} · {row.eligible ? "Eligible" : "Blocked"}</small></span>
            </label>)}</div>
            <Pagination data={options.data} onChange={setPage} label="Budget campaign pages" />
          </div>)}
        {ids.length > 0 && <div className="budget-panel-body budget-selected">
          {ids.map((id, index) => <Button variant="outline" type="button" key={id} onClick={() => choose(id)}
            aria-label={`Remove ${selected[index]?.campaign_name ?? `campaign ${id}`}`}>
            {selected[index]?.campaign_name ?? `Campaign #${id}`} <span aria-hidden="true">×</span>
          </Button>)}
        </div>}
        {selectedLoading && <Loading label="Loading selected benchmarks…" />}
        {selectedError && <ErrorPanel error={selectedError} retry={() => {
          selectedQueries.forEach(query => { if (query.isError) void query.refetch() })
        }} />}
        {missingSelection && <div className="budget-panel-body"><Notice>One or more campaigns are unavailable. Remove them to proceed.</Notice></div>}
      </Card>
      {rows.length > 0 && <Card className="table-card">
        <PanelHeading title="Observed campaign performance" description="Review persisted reporting and eligibility before allocating spend." />
        <HistoricalTable rows={rows} />
        <BenchmarkNotes rows={rows} />
      </Card>}
      <Card className="table-card">
        <PanelHeading title="Budget allocation" description="Editing an entry leaves the other allocations unchanged. Assign the remainder or adjust the entries to balance." />
        <div className="budget-panel-body budget-allocation-actions">
          <SelectField label="Allocation method" value={mode} onChange={changeMode}>
            <option value="DOLLARS">Dollars (USD)</option><option value="PERCENT">Percentage (%)</option>
          </SelectField>
          <Button type="button" variant="outline" disabled={!canAllocate} onClick={() => preset.mutate({ ...selection, method: "historical" })}>Restore historical allocation</Button>
          <Button type="button" variant="outline" disabled={!canAllocate} onClick={() => preset.mutate({ ...selection, method: "equal" })}>Equal allocation</Button>
        </div>
        {preset.error && <ErrorPanel error={preset.error} />}
        {rows.length > 0 && <div className="table-scroll"><table className="data-table" aria-label="Budget allocation inputs">
          <thead><tr><th scope="col">Campaign</th><th scope="col">{mode === "DOLLARS" ? "Dollars (USD)" : "Share (%)"}</th><th scope="col">Share of total</th></tr></thead>
          <tbody>{rows.map(row => {
            const key = row.campaign_id
            const enteredUnits = units(values[key] ?? "0")
            const width = target && enteredUnits != null ? Math.min(100, 100 * enteredUnits / target) : 0
            return <tr key={key}>
              <th scope="row">{row.campaign_name} <small className="table-secondary"><PlatformBadge platform={row.platform} /></small></th>
              <td><input className="budget-amount" aria-label={`${row.campaign_name} allocation`} aria-invalid={enteredUnits == null}
                inputMode="decimal" value={values[key] ?? "0"} maxLength={12}
                disabled={!row.eligible && enteredUnits === 0} onChange={event => {
                  setNotice("")
                  setValues({ ...values, [key]: event.currentTarget.value })
                }} />{!row.eligible && <small className="table-secondary budget-blocked">Blocked · allocation must be zero</small>}</td>
              <td><div className="budget-track" aria-hidden="true"><span style={{ width: `${width}%` }} /></div></td>
            </tr>
          })}</tbody>
        </table></div>}
        <div className="budget-panel-body budget-balance">
          <p role="status">{mode === "DOLLARS" && budgetIssue ? "Enter a valid total budget to see the remaining amount." :
            remaining == null ? "Enter valid allocations with up to two decimal places." :
            `${remaining >= 0 ? "Remaining" : "Over budget"} · ${mode === "DOLLARS" ? "$" : ""}${unitInput(Math.abs(remaining))}${mode === "PERCENT" ? "%" : ""}`}</p>
          {canAllocate && eligible.length > 0 && remaining != null && remaining !== 0 &&
            <Button variant="outline" type="button" onClick={balance}>Balance with {eligible.at(-1)?.campaign_name}</Button>}
          {notice && <Notice>{notice}</Notice>}
        </div>
      </Card>
      <Card>
        <PanelHeading title="Scenario assumptions" description="Edit each case independently. Positive CPA adjustments imply higher cost per attributed purchase." />
        <div className="budget-panel-body budget-assumptions">
          <SelectField label="Assumption case" value={active} onChange={value => setActive(value as BudgetCase)}>
            {cases.map(item => <option key={item} value={item}>{caseNames[item]}</option>)}
          </SelectField>
          <div className="budget-controls">{assumptionFields.map(({ key, label, min, max, help }) =>
            <Field key={key} label={label} help={`${help} Range ${min}% to +${max}%.`} value={assumptions[active][key]}
              inputMode="decimal" maxLength={7} onChange={event =>
                setAssumptions({ ...assumptions, [active]: { ...assumptions[active], [key]: event.currentTarget.value } })} />)}</div>
        </div>
      </Card>
      <div>
        <div className="budget-run-controls">
          <Button type="button" disabled={!validPlan || calculate.isPending}
            aria-describedby="budget-calculate-requirements budget-calculate-error" onClick={() => { save.reset(); calculate.mutate(plan) }}>
            {calculate.isPending ? "Calculating…" : "Calculate scenarios"}
          </Button>
          <Button type="button" variant="outline" disabled={!current || !validPlan || calculate.isPending}
            aria-describedby="budget-calculate-requirements budget-save-requirements budget-calculate-error budget-save-error"
            onClick={() => current && save.mutate(current.evidence_fingerprint)}>{save.isPending ? "Saving…" : "Save scenario"}</Button>
        </div>
        <ActionRequirements id="budget-calculate-requirements" heading="Before calculating" items={requirements} />
        <ActionRequirements id="budget-save-requirements" heading="Before saving"
          items={current || calculate.isPending || requirements.length ? [] : [
            calculate.data ? "Calculate again to save the current draft." : "Calculate scenarios before saving.",
          ]} />
        {calculate.error && <Notice id="budget-calculate-error">{calculate.error.message}</Notice>}
        {save.error && <Notice id="budget-save-error">{save.error.message}</Notice>}
      </div>
    </fieldset>
    {current ? <BudgetResults result={current} plan={plan} /> :
      <Empty title="No modeled results yet" description="Choose at least two eligible campaigns and balance the allocation to calculate three scenarios." />}
  </>
}
