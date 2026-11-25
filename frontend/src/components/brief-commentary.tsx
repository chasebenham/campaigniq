import { useRef, useState, type Dispatch, type SetStateAction } from "react"
import { useMutation, useQuery } from "@tanstack/react-query"
import { Sparkles } from "lucide-react"

import { PanelHeading } from "@/components/shared"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { ai } from "@/lib/ai"
import { briefs, type CommentaryRequest, type CommentaryResult, type CommentaryTarget, type Draft, type Narrative } from "@/lib/briefs"

const fields: { key: keyof Narrative; label: string; hint: string }[] = [
  { key: "executive_summary", label: "Executive summary", hint: "Leave blank to use a short, data-driven overview." },
  { key: "recommendations", label: "Strategic recommendations", hint: "State actions under consideration and their supporting evidence." },
  { key: "commentary", label: "Management commentary", hint: "Record business context or unresolved questions." },
  { key: "experiment", label: "Management experiment proposal", hint: "Include a hypothesis, change, comparator, metrics, guardrails, measurement window, and risks where known." },
  { key: "next_decisions", label: "Next decisions", hint: "Describe what leadership should review or decide." },
]
const entries = (target: CommentaryTarget) => fields.filter(field => target === "all" || field.key === target)
const sourceKey = (draft: Draft) => JSON.stringify([draft.sources, Boolean(draft.refresh_evidence), Boolean(draft.allow_historical)])

export function BriefCommentary({ draft, setDraft, id, dateIssue, initialProvenance, stale, previewFingerprint, busy, savedProposal }: {
  draft: Draft
  setDraft: Dispatch<SetStateAction<Draft>>
  id?: string
  dateIssue: string
  initialProvenance?: CommentaryResult["provenance"]
  stale: boolean
  previewFingerprint?: string
  busy: boolean
  savedProposal?: { id: number; text: string }
}) {
  const availability = useQuery({ queryKey: ["ai", "availability"], queryFn: ({ signal }) => ai.availability(signal) })
  const initial = useRef(sourceKey(draft))
  const scope = sourceKey(draft)
  const latest = useRef({ draft, busy, scope, revision: 0 })
  latest.current = { draft, busy, scope, revision: latest.current.revision + Number(latest.current.scope !== scope) }
  const [provenance, setProvenance] = useState(initialProvenance ?? {})
  const [generated, setGenerated] = useState<Partial<Narrative>>(() => Object.fromEntries(fields
    .filter(({ key }) => initialProvenance?.[key]?.authorship === "AI_GENERATED")
    .map(({ key }) => [key, draft.narrative[key]])))
  const [keys, setKeys] = useState<Partial<Record<keyof Narrative, string>>>({})
  const [confirmation, setConfirmation] = useState<CommentaryTarget>()
  const [held, setHeld] = useState<{ data: CommentaryResult; key: string; changedSources: boolean }>()
  const [message, setMessage] = useState("")
  const inFlight = useRef(false)

  function apply(data: CommentaryResult, key: string) {
    const included = Object.keys(data.fields) as (keyof Narrative)[]
    setDraft(old => ({
      ...old,
      summary_attempt_id: data.fields.executive_summary ? null : old.summary_attempt_id,
      narrative: { ...old.narrative, ...data.fields },
      commentary_attempt_ids: {
        ...old.commentary_attempt_ids,
        ...Object.fromEntries(included.map(field => [field, data.provenance[field]!.id])),
      },
    }))
    setProvenance(old => ({ ...old, ...data.provenance }))
    setGenerated(old => ({ ...old, ...data.fields }))
    setKeys(old => ({ ...old, ...Object.fromEntries(included.map(field => [field, key])) }))
    setHeld(undefined)
    setMessage(data.fields.executive_summary && included.length > 1 ? "All five drafts are ready to review." : "Draft added. Review or edit it before saving.")
  }

  const draftText = useMutation({
    mutationFn: ({ body }: { body: CommentaryRequest; key: string; revision: number; before: Narrative }) => briefs.draftCommentary(body),
    onSuccess: (data, request) => {
      const current = latest.current
      const changedSources = current.revision !== request.revision
      const changedText = entries(request.body.target).some(({ key }) => current.draft.narrative[key] !== request.before[key])
      if (changedSources || changedText || current.busy) {
        setHeld({ data, key: request.key, changedSources })
        setMessage(changedSources
          ? "Evidence selections changed during drafting. The returned text is available for review. Regenerate for the current evidence."
          : "The editor changed during drafting. Review the returned draft before replacing any text.")
      } else apply(data, request.key)
    },
    onSettled: () => { inFlight.current = false },
  })

  function start(target: CommentaryTarget) {
    if (inFlight.current || busy || dateIssue || !availability.data?.enabled) return
    inFlight.current = true
    setConfirmation(undefined)
    setHeld(undefined)
    setMessage("")
    draftText.mutate({
      body: {
        target, request_id: crypto.randomUUID(), brief_id: id ? Number(id) : undefined,
        sources: draft.sources, allow_historical: draft.allow_historical,
        base_version: draft.base_version, refresh_evidence: draft.refresh_evidence,
      },
      key: scope, revision: latest.current.revision, before: draft.narrative,
    })
  }

  function request(target: CommentaryTarget) {
    if (entries(target).some(({ key }) => draft.narrative[key].trim())) setConfirmation(target)
    else start(target)
  }

  function edit(key: keyof Narrative, value: string) {
    setDraft(old => ({
      ...old,
      narrative: { ...old.narrative, [key]: value },
    }))
  }

  function applySavedProposal() {
    if (!savedProposal) return
    setDraft(old => {
      const attempts = { ...old.commentary_attempt_ids }
      delete attempts.executive_summary
      return { ...old, summary_attempt_id: savedProposal.id, commentary_attempt_ids: attempts,
        narrative: { ...old.narrative, executive_summary: savedProposal.text } }
    })
  }

  const enabled = availability.data?.enabled === true
  const pending = draftText.isPending ? draftText.variables.body.target : undefined
  const disabled = !enabled || Boolean(dateIssue) || Boolean(pending) || busy

  return <Card>
    <PanelHeading title="Executive commentary" description="Draft with verified evidence, then review and edit before saving.">
      <Button variant="outline" disabled={disabled} onClick={() => request("all")}>
        <Sparkles size={15} aria-hidden="true" />{pending === "all" ? "Drafting all five…" : "Draft All Five"}
      </Button>
    </PanelHeading>
    {!enabled && <p className="brief-form-row support-text">
      {availability.isPending ? "Checking AI availability…" : "AI drafting is unavailable. You can write or edit all five fields manually."}
    </p>}
    {enabled && dateIssue && <p className="brief-form-row support-text">{dateIssue} Valid reporting dates are required for AI drafting.</p>}
    {savedProposal && savedProposal.id !== draft.summary_attempt_id && <div className="brief-form-row brief-wrap">
      <span className="support-text">A saved AI proposal is available. Applying it replaces only the executive summary in this editor.</span>
      <Button variant="outline" disabled={Boolean(pending)} onClick={applySavedProposal}>Replace executive summary with saved proposal</Button>
    </div>}
    {confirmation && <div className="brief-form-row brief-wrap commentary-confirmation" role="group" aria-label="Confirm commentary replacement">
      <span>Replace existing text in {entries(confirmation).filter(({ key }) => draft.narrative[key].trim()).map(({ label }) => label).join(", ")} with AI drafts?</span>
      <Button variant="outline" onClick={() => setConfirmation(undefined)}>Keep current text</Button>
      <Button disabled={disabled} onClick={() => start(confirmation)}>Replace and draft</Button>
    </div>}
    {message && <p className="brief-form-row support-text" role="status">{message}</p>}
    {draftText.error && <p className="brief-form-row action-error" role="alert">{draftText.error.message} No commentary was replaced.</p>}
    {held && <div className="brief-form-row commentary-held">
      <details><summary>Review returned draft</summary>
        {fields.filter(({ key }) => held.data.fields[key]).map(({ key, label }) =>
          <div key={key}><strong>{label}</strong><p>{held.data.fields[key]}</p></div>)}
      </details>
      {!held.changedSources && held.key === scope &&
        <Button variant="outline" disabled={Boolean(pending)} onClick={() => apply(held.data, held.key)}>Apply returned draft</Button>}
    </div>}
    <div className="brief-narrative">
      {fields.map(({ key, label, hint }) => {
        const meta = draft.commentary_attempt_ids?.[key] ? provenance[key] : undefined
        const legacy = key === "executive_summary" && Boolean(draft.summary_attempt_id) && !meta
        const hasText = Boolean(draft.narrative[key].trim())
        const changed = meta && generated[key] != null ? draft.narrative[key] !== generated[key] : meta?.authorship === "AI_EDITED_BY_MANAGEMENT"
        const outdated = meta ? meta.stale || (keys[key] ?? initial.current) !== scope
          || (!keys[key] && stale) || Boolean(previewFingerprint && meta.evidence_fingerprint !== previewFingerprint)
          : legacy && (stale || initial.current !== scope)
        return <div className="commentary-field" key={key}>
          <div className="commentary-field-top">
            <label className="filter-field" htmlFor={`brief-${key}`}>{label}</label>
            <Button variant="outline" className="commentary-ai-button" disabled={disabled}
              aria-label={`${outdated && hasText ? "Regenerate" : "Generate"} ${label} with AI`}
              onClick={() => request(key)}>
              {pending === key ? "Drafting…" : outdated && hasText ? "Regenerate with AI" : "Generate with AI"}
            </Button>
          </div>
          <textarea id={`brief-${key}`} aria-describedby={`brief-${key}-hint`} maxLength={2000} rows={4}
            value={draft.narrative[key]} onChange={event => edit(key, event.currentTarget.value)} />
          <small id={`brief-${key}-hint`}>{hint}</small>
          {hasText && meta && <small>{changed ? "AI draft · edited by management" : "AI draft · review before saving"} · {meta.model}</small>}
          {hasText && legacy && <small>Saved AI proposal · review before saving</small>}
          {hasText && outdated && <small className="budget-blocked">Drafted against earlier evidence. Review or regenerate.</small>}
        </div>
      })}
    </div>
  </Card>
}
