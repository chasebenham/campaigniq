import { request, type Attribution, type Decimal, type Metrics, type Page, type Platform } from "./api"

export type Policy = "D-01" | "D-02" | "D-03" | "D-04" | "D-05" | "D-06"
export type Severity = "HIGH" | "MEDIUM" | "LOW" | "INFORMATIONAL"
export type FindingCategory = "PERFORMANCE_RISK" | "OPTIMIZATION_OPPORTUNITY" | "DATA_QUALITY"
export type FindingState = "CURRENT" | "STALE" | "HISTORICAL"
export type Window = { start: string; end: string }

export interface DetectionRun {
  id: number
  started_at: string
  finished_at: string
  evaluation_date: string
  windows: { current: Window; baseline: Window; history: Window; maturation_days: number }
  policy_version: string
  state: FindingState | null
  status: "COMPLETED" | "FAILED"
  campaign_count: number
  finding_count: number
  suppression_count: number
  errors: { code: string; message: string }[]
  reused: boolean
}

export interface PeriodEvidence extends Window {
  calendar_days: number
  expected_days: number
  observed_days: number
  fictional_days: number
  missing_dates: string[]
  complete: boolean
  metrics: Metrics | null
}

export interface Finding {
  id: number
  run_id: number
  campaign_id: number
  policy_id: Policy
  policy_version: string
  category: FindingCategory
  severity: Severity
  summary: string
  classification_reason: string
  current_evidence: PeriodEvidence
  baseline_evidence: PeriodEvidence | null
  campaign_snapshot: {
    campaign_name: string
    platform: Platform
    objective: string
    external_campaign_id: string
    target_cpa: Decimal | null
    target_roas: Decimal | null
  }
  thresholds: Record<string, unknown>
  observations: Record<string, unknown>
  reporting_context: Attribution[]
  evidence_quality: "BLOCKED" | "LIMITED" | "SUFFICIENT"
  data_quality_flags: { code: string; period: string; message: string; dates: string[]; blocking: boolean }[]
  limitations: string[]
  created_at: string
  state: FindingState
}

export interface Suppression {
  id: number
  run_id: number
  campaign_id: number
  campaign_name: string
  platform: Platform
  policy_id: Policy
  reason_code: string
  explanation: string
  evidence: { current: PeriodEvidence; baseline: PeriodEvidence | null }
}

interface DetectionSummary {
  run: DetectionRun | null
  counts: Partial<Record<FindingCategory | "INSUFFICIENT_EVIDENCE", number>>
}

type Params = Record<string, string | number | undefined>

export const detection = {
  run: () => request<DetectionRun>("/detection/runs", undefined, { method: "POST" }),
  runs: (page: number, signal: AbortSignal) => request<Page<DetectionRun>>("/detection/runs", { page, page_size: 5 }, { signal }),
  summary: (signal: AbortSignal) => request<DetectionSummary>("/insights/summary", undefined, { signal }),
  findings: (params: Params, signal: AbortSignal) => request<Page<Finding>>("/insights", params, { signal }),
  finding: (id: string, signal: AbortSignal) => request<Finding>(`/insights/${encodeURIComponent(id)}`, undefined, { signal }),
  suppressions: (runId: number, params: Params, signal: AbortSignal) => request<Page<Suppression>>(
    `/detection/runs/${runId}/suppressions`, params, { signal },
  ),
}

export const categories: Record<FindingCategory, string> = {
  PERFORMANCE_RISK: "Performance risk",
  OPTIMIZATION_OPPORTUNITY: "Optimization opportunity",
  DATA_QUALITY: "Data quality",
}

export const policies: Record<Policy, string> = {
  "D-01": "CPA deterioration",
  "D-02": "ROAS below target",
  "D-03": "Purchase conversion rate decline",
  "D-04": "Spend without attributed purchases",
  "D-05": "Potential scaling opportunity",
  "D-06": "Reporting or data-quality issue",
}

export const severities: Record<Severity, string> = {
  HIGH: "High", MEDIUM: "Medium", LOW: "Low", INFORMATIONAL: "Informational",
}

export const states: Record<FindingState, string> = {
  CURRENT: "Current", STALE: "Stale", HISTORICAL: "Historical",
}
