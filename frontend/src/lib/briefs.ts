import { request, type Page } from "./api"
import type { Finding, Window } from "./detection"

export interface Narrative {
  executive_summary: string
  recommendations: string
  commentary: string
  next_decisions: string
  experiment: string
}

export const emptyNarrative: Narrative = {
  executive_summary: "", recommendations: "", commentary: "", next_decisions: "", experiment: "",
}

export interface Sources {
  period: Window
  findings: { finding_id: number; analysis_id?: number | null }[]
  budget_id?: number | null
}

export interface Draft {
  title: string
  sources: Sources
  narrative: Narrative
  allow_historical: boolean
  summary_attempt_id?: number | null
  base_version?: number | null
  refresh_evidence?: boolean
  commentary_attempt_ids?: Partial<Record<keyof Narrative, number>>
}

export interface CommentaryProvenance {
  id: number
  model: string
  prompt_version: string
  schema_version: string
  evidence_fingerprint: string
  generated_at: string
  usage: Record<string, unknown> | null
  references: string[]
  authorship: "AI_GENERATED" | "AI_EDITED_BY_MANAGEMENT"
  stale: boolean
}
export type CommentaryTarget = keyof Narrative | "all"
export type CommentaryResult = {
  fields: Partial<Narrative>
  provenance: Partial<Record<keyof Narrative, CommentaryProvenance>>
}
export type CommentaryRequest = Pick<Draft, "sources" | "allow_historical" | "base_version" | "refresh_evidence"> & {
  target: CommentaryTarget
  request_id: string
  brief_id?: number
}

interface AnalysisOption {
  id: number
  model: string
  historical: boolean
  created_at: string
}

export interface FindingOption {
  finding: Finding
  analyses: AnalysisOption[]
  suggested: boolean
}

export type SourceKind = "verified" | "ai" | "management" | "modeled"
export interface ReportTable { headers: string[]; rows: string[][]; caption: string | null }
export interface Block {
  title: string | null
  paragraphs: string[]
  bullets: string[]
  tables: ReportTable[]
  source: SourceKind | null
}
export interface Document {
  title: string
  period: Window
  generated_at: string
  template_version: string
  provenance: string
  sections: { title: string; blocks: Block[] }[]
}
export interface Preview { document: Document; evidence_fingerprint: string; warnings: string[] }
export interface BriefSummary {
  id: number
  title: string
  period: Window
  current_version: number
  created_at: string
  updated_at: string
  status: "SAVED"
  freshness: "CURRENT" | "STALE"
}
interface VersionSummary {
  version: number
  title: string
  period: Window
  generated_at: string
  evidence_fingerprint: string
  template_version: string
}
export interface Proposal {
  id: number
  version: number
  status: "PENDING" | "COMPLETED" | "FAILED" | "STALE"
  model: string
  text: string | null
  references: string[]
  usage: Record<string, unknown> | null
  error: string | null
}
export interface VersionView extends Preview, VersionSummary {
  brief_id: number
  current_version: number
  freshness: BriefSummary["freshness"]
  draft: Draft
  generation: Proposal | null
  commentary_provenance?: CommentaryResult["provenance"]
}

const root = "/strategy-briefs"
const route = (id: string, ending = "") => `${root}/${encodeURIComponent(id)}${ending}`
function send<T>(path: string, body: unknown, method = "POST") {
  return request<T>(path, undefined, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
}

export const briefs = {
  defaults: (signal: AbortSignal) => request<{ period: Window | null; suggested_run_id: number | null }>(`${root}/defaults`, undefined, { signal }),
  sources: (period: Window, page: number, signal: AbortSignal) => request<{ suggested_run_id: number | null; findings: Page<FindingOption> }>(
    `${root}/sources`, { ...period, page, page_size: 8 }, { signal },
  ),
  list: (page: number, signal: AbortSignal) => request<Page<BriefSummary>>(root, { page }, { signal }),
  read: (id: string, version: string | undefined, signal: AbortSignal) =>
    request<VersionView>(route(id, version ? `/versions/${encodeURIComponent(version)}` : ""), undefined, { signal }),
  versions: (id: string, page: number, signal: AbortSignal) => request<Page<VersionSummary>>(
    route(id, "/versions"), { page, page_size: 6 }, { signal },
  ),
  preview: (draft: Draft, id?: string) => send<Preview>(id ? route(id, "/preview") : `${root}/preview`, draft),
  save: (draft: Draft, evidence_fingerprint: string, id?: string) =>
    send<VersionView>(id ? route(id) : root, { ...draft, evidence_fingerprint }, id ? "PUT" : "POST"),
  generate: (id: string, version: number) => send<Proposal>(route(id, "/generate-summary"), { version }),
  draftCommentary: (body: CommentaryRequest) => send<CommentaryResult>(`${root}/draft-commentary`, body),
  pdf: (id: number, version: number) => `/api/v1${route(String(id), "/export/pdf")}?version=${version}`,
}
