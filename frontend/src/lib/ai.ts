import { request, type Page } from "./api"

export type Action = "INVESTIGATE" | "TEST" | "MONITOR" | "CONSIDER_REALLOCATION"
export type AnalysisStatus = "PENDING" | "COMPLETED" | "STALE" | "FAILED"

export interface Availability {
  enabled: boolean
  reason: "DISABLED" | "MISSING_API_KEY" | "PROVIDER_ERROR" | null
  request_limit_per_hour: number
  provider_max_attempts: number
  model: string
  provider_status: "UNCHECKED" | "ACCESSIBLE" | "ERROR"
  provider_error_code: string | null
  provider_message: string | null
}

export interface Analysis {
  id: number
  finding_id: number
  model: string
  prompt_version: string
  schema_version: string
  status: AnalysisStatus
  created_at: string
  finished_at: string | null
  structured_output: AnalysisOutput | null
  evidence_references: { path: string; value: string | number | boolean }[]
  provider_usage: { input_tokens?: number; output_tokens?: number; total_tokens?: number } | null
  error_message: string | null
  is_current: boolean
}

interface AnalysisOutput {
  finding_id: number
  executive_summary: string
  business_impact_assessment: string
  evidence_references: string[]
  possible_explanations: string[]
  missing_information: string[]
  recommended_action_type: Action
  recommended_action: string
  action_rationale?: string
  experiment_hypothesis: string | null
  proposed_experiment: {
    design: string; audience_or_scope: string; duration: string; guardrails: string; decision_rule: string
    proposed_change?: string; comparison?: string; guardrail_metrics?: string[]
  } | null
  primary_success_metric: string | null
  secondary_metrics: string[]
  risks_and_limitations: string[]
  confidence_rationale: string
}

type AnalysisRequest = { id: string; regeneration?: { regenerate_from: number; request_id: string } }

export const ai = {
  availability: (signal: AbortSignal) => request<Availability>("/ai/status", undefined, { signal }),
  check: () => request<Availability>("/ai/status/check", undefined, { method: "POST" }),
  analyze: ({ id, regeneration }: AnalysisRequest) => request<Analysis>(`/insights/${encodeURIComponent(id)}/analyses`, undefined, {
    method: "POST",
    ...(regeneration ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(regeneration) } : {}),
  }),
  history: (id: string, page: number, signal: AbortSignal) => request<Page<Analysis>>(
    `/insights/${encodeURIComponent(id)}/analyses`, { page, page_size: 8 }, { signal },
  ),
}

export const actionLabels: Record<Action, string> = {
  INVESTIGATE: "Investigate", TEST: "Test", MONITOR: "Monitor", CONSIDER_REALLOCATION: "Consider reallocation",
}

export const unavailableMessages = {
  DISABLED: "AI analysis is disabled for this workspace.",
  MISSING_API_KEY: "AI analysis needs an OpenAI API key configured on the server.",
  PROVIDER_ERROR: "OpenAI reported a connection or account issue.",
}
