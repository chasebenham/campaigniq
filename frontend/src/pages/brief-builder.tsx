import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link, useNavigate, useParams, useSearchParams } from "react-router"

import { BriefDocument } from "@/components/brief-document"
import { BriefCommentary } from "@/components/brief-commentary"
import { SelectField } from "@/components/filters"
import { ActionRequirements, ErrorPanel, Loading, PageHeading, Pagination, PanelHeading, PlatformBadge } from "@/components/shared"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { ApiError } from "@/lib/api"
import { budgetApi } from "@/lib/budget"
import { briefs, emptyNarrative, type CommentaryResult, type Draft, type Sources } from "@/lib/briefs"
import { detection, severities, states } from "@/lib/detection"
import { dateLabel, dateRange } from "@/lib/presentation"

const idOf = (value: string | null) => value && /^\d{1,10}$/.test(value) && Number(value) > 0 && Number(value) <= 2_147_483_647 ? Number(value) : undefined

export function BriefBuilder() {
  const { briefId } = useParams()
  const [params] = useSearchParams()
  const linkedFinding = briefId ? undefined : idOf(params.get("finding_id"))
  const linkedAnalysis = linkedFinding ? idOf(params.get("analysis_id")) : undefined
  const linkedBudget = briefId ? undefined : idOf(params.get("budget_id"))
  const selectedProposal = idOf(params.get("summary_attempt"))
  const defaults = useQuery({ queryKey: ["briefs", "defaults"], enabled: !briefId, queryFn: ({ signal }) => briefs.defaults(signal) })
  const finding = useQuery({
    queryKey: ["detection", "finding", String(linkedFinding)], enabled: Boolean(linkedFinding),
    queryFn: ({ signal }) => detection.finding(String(linkedFinding), signal),
  })
  const version = useQuery({
    queryKey: ["briefs", "report", briefId], enabled: Boolean(briefId),
    queryFn: ({ signal }) => briefs.read(briefId!, undefined, signal),
  })
  const proposal = version.data?.generation
  const usingProposal = selectedProposal && proposal?.id === selectedProposal && proposal.status === "COMPLETED" && proposal.text
  const linked = finding.data
  const linkedPeriod = linked?.current_evidence
  const original = version.data?.draft
  const savedProposal = usingProposal && proposal?.text ? { id: proposal.id, text: proposal.text } : undefined
  const fillEmptySummary = savedProposal && !original?.narrative.executive_summary.trim()
  const period = linkedPeriod ?? defaults.data?.period
  const initial = original ? {
    ...original,
    ...(fillEmptySummary ? {
      summary_attempt_id: savedProposal.id,
      narrative: { ...original.narrative, executive_summary: savedProposal.text },
    } : {}),
  } : {
    title: "Paid Media Strategy Brief",
    sources: {
      period: { start: period?.start ?? "", end: period?.end ?? "" },
      findings: [], budget_id: null,
    },
    narrative: emptyNarrative, allow_historical: false,
  }
  return <>
    <Link to={briefId ? `/strategy-briefs/${briefId}` : "/strategy-briefs"} className="parent-link text-link">
      {briefId ? "Back to saved report" : "Strategy Briefs"}
    </Link>
    <PageHeading title={briefId ? "Revise strategy brief" : "Create strategy brief"}
      description="Select evidence, add leadership commentary, then preview and save a version." />
    {(briefId ? version.isPending : defaults.isPending || (linkedFinding && finding.isPending)) ?
      <Loading label="Loading report sources…" /> : (defaults.error || version.error || finding.error) ?
      <ErrorPanel error={(defaults.error || version.error || finding.error)!} /> :
      <Builder key={`${briefId ?? "new"}-${params.toString()}`} id={briefId} initial={initial}
        linkedFinding={linked?.id} linkedAnalysis={linkedAnalysis} linkedCampaign={linked?.campaign_snapshot.campaign_name}
        linkedBudget={linkedBudget} stale={version.data?.freshness === "STALE"}
        initialProvenance={version.data?.commentary_provenance} savedProposal={savedProposal} />}
  </>
}

function Builder({ id, initial, linkedFinding, linkedAnalysis, linkedCampaign, linkedBudget, stale, initialProvenance, savedProposal }: {
  id?: string; initial: Draft; linkedFinding?: number; linkedAnalysis?: number; linkedCampaign?: string
  linkedBudget?: number; stale: boolean; initialProvenance?: CommentaryResult["provenance"]
  savedProposal?: { id: number; text: string }
}) {
  const [draft, setDraft] = useState<Draft>(initial)
  const [findingPage, setFindingPage] = useState(1)
  const [budgetPage, setBudgetPage] = useState(1)
  const navigate = useNavigate()
  const cache = useQueryClient()
  const { period, findings, budget_id } = draft.sources
  const days = (Date.parse(period.end) - Date.parse(period.start)) / 86_400_000
  const missingDates = [!period.start && "reporting start date", !period.end && "reporting end date"].filter(Boolean)
  const dateIssue = missingDates.length ? `Enter the ${missingDates.join(" and ")}.` :
    days < 0 ? "Choose a reporting end date on or after the start date." :
    !(days < 90) ? "Choose a reporting period of 1 to 90 calendar days." :
    period.end >= new Date().toISOString().slice(0, 10) ? "Choose a reporting end date before today (UTC)." : ""
  const datesValid = !dateIssue
  const requirements = [!draft.title.trim() ? "Enter a report title." : "", dateIssue].filter(Boolean)
  const sourceOptions = useQuery({
    queryKey: ["briefs", "sources", period, findingPage], enabled: datesValid,
    queryFn: ({ signal }) => briefs.sources(period, findingPage, signal),
  })
  const budgets = useQuery({ queryKey: ["budget", "scenarios", budgetPage], queryFn: ({ signal }) => budgetApi.scenarios(budgetPage, signal) })
  const preview = useMutation({ mutationFn: (value: Draft) => briefs.preview(value, id) })
  const matchesPreview = JSON.stringify(preview.variables) === JSON.stringify(draft)
  const reviewed = matchesPreview ? preview.data : undefined
  const previewIssue = matchesPreview ? preview.error : null
  const save = useMutation({
    mutationFn: () => briefs.save(draft, reviewed!.evidence_fingerprint, id),
    onError: error => {
      if (error instanceof ApiError && error.code === "EVIDENCE_CHANGED") preview.reset()
    },
    onSuccess: saved => {
      cache.setQueryData(["briefs", "report", String(saved.brief_id)], saved)
      void cache.invalidateQueries({ queryKey: ["briefs", "list"] })
      void cache.invalidateQueries({ queryKey: ["briefs", "versions", String(saved.brief_id)] })
      navigate(`/strategy-briefs/${saved.brief_id}`)
    },
  })
  function changeSources(delta: Partial<Sources>) {
    setDraft(old => ({ ...old, sources: { ...old.sources, ...delta } }))
  }
  function changeDate(key: "start" | "end", value: string) {
    changeSources({ period: { ...period, [key]: value } })
    setFindingPage(1)
  }
  function toggle(finding_id: number, analysis_id?: number) {
    changeSources({ findings: findings.some(row => row.finding_id === finding_id)
      ? findings.filter(row => row.finding_id !== finding_id) : [...findings, { finding_id, analysis_id }] })
  }
  function chooseAnalysis(finding_id: number, value: string) {
    changeSources({ findings: findings.map(row => row.finding_id === finding_id ? { ...row, analysis_id: Number(value) || null } : row) })
  }
  const options = sourceOptions.data?.findings
  const selectedBudget = budgets.data?.items.find(row => row.id === budget_id)
  const updateBusy = preview.isPending || save.isPending
  return <>
    <fieldset className="brief-builder" disabled={updateBusy}>
      <Card>
        <PanelHeading title="Report scope" description="A basic brief needs a title and reporting dates. Findings, AI analyses, budget scenarios, and commentary are optional." />
        <div className="brief-form-row">
          <label className="filter-field brief-field-wide">Report title<input required maxLength={120} value={draft.title}
            onChange={event => setDraft({ ...draft, title: event.currentTarget.value })} /></label>
          <label className="filter-field">Reporting start<input required type="date" value={period.start} onChange={event => changeDate("start", event.currentTarget.value)} /></label>
          <label className="filter-field">Reporting end<input required type="date" min={period.start || undefined} value={period.end}
            onChange={event => changeDate("end", event.currentTarget.value)} /></label>
        </div>
        {dateIssue && <p className="brief-form-row support-text">{dateIssue}</p>}
        {id && <label className="brief-form-row brief-check">
          <input type="checkbox" checked={Boolean(draft.refresh_evidence)}
            onChange={event => setDraft({ ...draft, refresh_evidence: event.currentTarget.checked })} />
          <span>Refresh verified evidence{stale ? " (saved evidence has changed)" : ""}<small>Commentary-only revisions otherwise reuse the saved source snapshot.</small></span>
        </label>}
      </Card>
      <Card className="table-card">
        <PanelHeading title="Verified findings" description={sourceOptions.data?.suggested_run_id
          ? `Run #${sourceOptions.data.suggested_run_id} has up to three suggested findings. Choose up to eight.`
          : "Choose up to eight findings with evaluated windows inside the reporting period."}>
          <span className="support-text">{findings.length} selected</span>
        </PanelHeading>
        {linkedFinding && !findings.some(row => row.finding_id === linkedFinding) && <div className="brief-form-row">
          <Button variant="outline" disabled={findings.length >= 8} onClick={() => toggle(linkedFinding, linkedAnalysis)}>
            {linkedAnalysis ? `Include linked analysis #${linkedAnalysis}` : `Include linked finding for ${linkedCampaign}`}
          </Button>
        </div>}
        {datesValid && (sourceOptions.isPending ? <Loading label="Loading eligible findings…" /> :
          sourceOptions.isError ? <ErrorPanel error={sourceOptions.error} retry={() => void sourceOptions.refetch()} /> :
          options?.items.length ? <div className="table-scroll" role="region" tabIndex={0} aria-label="Findings and accepted analyses">
            <table className="data-table">
              <thead><tr><th scope="col">Finding</th><th scope="col">Priority and evidence</th><th scope="col">Accepted AI analysis</th></tr></thead>
              <tbody>{options.items.map(({ finding, analyses, suggested }) => {
                const selected = findings.find(row => row.finding_id === finding.id)
                return <tr key={finding.id}>
                  <th scope="row"><label className="brief-check">
                    <input type="checkbox" checked={Boolean(selected)} disabled={!selected && findings.length >= 8} onChange={() => toggle(finding.id)} />
                    <span>{finding.campaign_snapshot.campaign_name}<small>{finding.summary}</small></span>
                  </label></th>
                  <td><PlatformBadge platform={finding.campaign_snapshot.platform} />
                    <small className="table-secondary">{finding.policy_id} · {severities[finding.severity]} · {states[finding.state]}{suggested ? " · Suggested" : ""}</small>
                    <small className="table-secondary">{dateRange(finding.current_evidence.start, finding.current_evidence.end)}</small></td>
                  <td>{selected ? <SelectField label={`AI analysis for finding #${finding.id}`} value={String(selected.analysis_id ?? "")}
                    onChange={value => chooseAnalysis(finding.id, value)}>
                    <option value="">Verified evidence only</option>
                    {selected.analysis_id && !analyses.some(row => row.id === selected.analysis_id) &&
                      <option value={selected.analysis_id}>Analysis #{selected.analysis_id} · Linked</option>}
                    {analyses.map(row => <option value={row.id} key={row.id}>#{row.id} · {row.model} · {dateLabel(row.created_at)}{row.historical ? " · Historical" : ""}</option>)}
                  </SelectField> : <span className="support-text">{analyses.length ? "Available after selection" : "None accepted"}</span>}</td>
                </tr>
              })}</tbody>
            </table>
          </div> : <p className="brief-form-row support-text">No detection findings have an evaluation window inside those dates.</p>)}
        {options && <Pagination data={options} onChange={setFindingPage} label="Finding pages" />}
        {findings.length > 0 && <div className="brief-form-row brief-wrap" aria-label="Selected findings">
          {findings.map(row => <Button variant="outline" key={row.finding_id} onClick={() => toggle(row.finding_id)}
            aria-label={`Remove finding #${row.finding_id}`}>Finding #{row.finding_id}{row.analysis_id ? ` · Analysis #${row.analysis_id}` : ""} ×</Button>)}
        </div>}
      </Card>
      <Card>
        <PanelHeading title="Saved Budget Lab scenario" description="Optional. The report preserves the saved budget model and its own reference dates." />
        <div className="brief-form-row brief-wrap">
          <SelectField label="Budget scenario" value={String(budget_id ?? "")} onChange={value => changeSources({ budget_id: Number(value) || null })}>
            <option value="">No budget scenario</option>
            {budget_id && !selectedBudget && <option value={budget_id}>Scenario #{budget_id}</option>}
            {budgets.data?.items.map(row => <option key={row.id} value={row.id}>{row.name}{row.status === "STALE" ? " · Stale" : ""}</option>)}
          </SelectField>
          {linkedBudget && budget_id !== linkedBudget && <Button variant="outline" onClick={() => changeSources({ budget_id: linkedBudget })}>Use linked scenario #{linkedBudget}</Button>}
        </div>
        {budgets.data && <Pagination data={budgets.data} onChange={setBudgetPage} label="Budget scenario pages" />}
        {budgets.isError && <ErrorPanel error={budgets.error} retry={() => void budgets.refetch()} />}
        <label className="brief-form-row brief-check">
          <input type="checkbox" checked={draft.allow_historical} onChange={event => setDraft({ ...draft, allow_historical: event.currentTarget.checked })} />
          <span>Include historical or stale sources I selected<small>The report labels these sources and preserves their saved evidence.</small></span>
        </label>
      </Card>
      <BriefCommentary draft={draft} setDraft={setDraft} id={id} dateIssue={dateIssue} busy={updateBusy}
        initialProvenance={initialProvenance} stale={stale} previewFingerprint={reviewed?.evidence_fingerprint}
        savedProposal={savedProposal} />
      <div>
        <div className="brief-wrap">
          <Button variant="outline" disabled={requirements.length > 0} aria-describedby="brief-preview-requirements brief-preview-error"
            onClick={() => { save.reset(); preview.mutate(draft) }}>
            {preview.isPending ? "Building preview…" : "Preview report"}
          </Button>
          <Button disabled={!reviewed || requirements.length > 0}
            aria-describedby="brief-preview-requirements brief-save-requirements brief-preview-error brief-save-error"
            onClick={() => save.mutate()}>{save.isPending ? "Saving…" : id ? "Save new version" : "Save strategy brief"}</Button>
        </div>
        <ActionRequirements id="brief-preview-requirements" heading="Before previewing" items={requirements} />
        <ActionRequirements id="brief-save-requirements" heading="Before saving"
          items={reviewed || preview.isPending || requirements.length || previewIssue ? [] : [
            preview.data ? "Preview your changes before saving." : "Select Preview report before saving.",
          ]} />
        {previewIssue && <p id="brief-preview-error" role="alert" className="action-error">
          <strong>Preview could not be built.</strong>{" "}
          {previewIssue instanceof ApiError && previewIssue.code === "HISTORICAL_SOURCE"
            ? "Select “Include historical or stale sources I selected” or remove those sources, then preview again."
            : previewIssue.message}
        </p>}
        {save.error && <p id="brief-save-error" role="alert" className="action-error"><strong>Brief could not be saved.</strong> {save.error.message}</p>}
      </div>
    </fieldset>
    {reviewed && <BriefDocument document={reviewed.document} />}
  </>
}
