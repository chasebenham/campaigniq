import { request, type Attribution, type Decimal, type Page, type Platform } from "./api"
import type { Finding, PeriodEvidence, Window } from "./detection"

export const cases = ["conservative", "base", "optimistic"] as const
export type BudgetCase = typeof cases[number]
export type Mode = "DOLLARS" | "PERCENT"
export const caseNames: Record<BudgetCase, string> = { conservative: "Conservative", base: "Base", optimistic: "Optimistic" }
export type CaseAssumption = { cpa_change_pct: string; marginal_cpa_change_pct: string; value_per_purchase_change_pct: string }
export type Assumptions = Record<BudgetCase, CaseAssumption>

export interface Defaults {
  reference: Window | null
  planning: Window
  assumptions: Assumptions
  mature_through: string
  earliest_planning_date: string
  minimum_observed_days: number
  maturation_days: number
  max_campaigns: number
}

export interface Benchmark {
  campaign_id: number
  campaign_name: string
  platform: Platform
  eligible: boolean
  blockers: string[]
  period: PeriodEvidence
  attribution_contexts: Attribution[]
  flags: Finding["data_quality_flags"]
  average_daily_spend: Decimal | null
  peak_daily_spend: Decimal | null
}

export interface Selection {
  reference: Window
  planning: Window
  campaign_ids: number[]
  total_budget: string
}
export type Allocation = { campaign_id: number; value: string }
export type AllocationRow = { campaign_id: number; dollars: Decimal; percent: Decimal }
export interface Plan extends Selection {
  name: string
  mode: Mode
  allocations: Allocation[]
  assumptions: Assumptions
  finding_id?: number | null
}

export interface Outcome {
  spend: Decimal
  purchases: Decimal | null
  value: Decimal | null
  cpa: Decimal | null
  roas: Decimal | null
}

interface ScenarioOutcome {
  portfolio: Outcome
  delta: Outcome
  versus_base: Outcome
  campaigns: { campaign_id: number; modeled: Outcome; delta: Outcome }[]
}

interface HistoricalAllocation {
  campaign_id: number
  observed_share_pct: Decimal
  normalized_share_pct: Decimal
  planned_share_pct: Decimal
  share_change_pct_points: Decimal
  normalized: Outcome
  planned_spend: Decimal
  spend_change: Decimal
  extrapolation: "none" | "modest" | "elevated" | "substantial" | null
}

export interface Calculation {
  model_version: string
  evidence_fingerprint: string
  reference_days: number
  planning_days: number
  maturation_days: number
  minimum_observed_days: number
  benchmarks: Benchmark[]
  allocation: HistoricalAllocation[]
  observed: Outcome
  normalized: Outcome
  scenarios: Record<BudgetCase, ScenarioOutcome>
  warnings: { code: string; message: string; campaign_id: number | null; scenario: BudgetCase | null; severity: "notice" | "warning" }[]
}

export interface ScenarioSummary {
  id: number
  name: string
  reference: Window
  planning: Window
  total_budget: Decimal
  created_at: string
  updated_at: string
  model_version: string
  evidence_fingerprint: string
  status: "CURRENT" | "STALE"
  cloned_from_id: number | null
}
export interface SavedScenario extends ScenarioSummary {
  plan: Plan
  result: Calculation
  calculated_at: string
}

type BenchmarkQuery = { start_date: string; end_date: string; platform?: string; q?: string; page?: number; campaign_id?: number }

function post<T>(path: string, body: unknown) {
  return request<T>(`/budget-lab${path}`, undefined, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  })
}

export const budgetApi = {
  defaults: (signal: AbortSignal) => request<Defaults>("/budget-lab/assumptions", undefined, { signal }),
  benchmarks: (params: BenchmarkQuery, signal: AbortSignal) => request<Page<Benchmark>>(
    "/budget-lab/eligible-campaigns", { ...params, page_size: 16 }, { signal },
  ),
  allocations: (body: Selection & ({ method: "historical" | "equal" } | { method: "convert"; mode: Mode; allocations: Allocation[] })) =>
    post<AllocationRow[]>("/allocations", body),
  calculate: (body: Plan) => post<Calculation>("/calculate", body),
  save: (plan: Plan, evidence_fingerprint: string) => post<SavedScenario>("/scenarios", { plan, evidence_fingerprint }),
  scenarios: (page: number, signal: AbortSignal) => request<Page<ScenarioSummary>>("/budget-lab/scenarios", { page, page_size: 8 }, { signal }),
  scenario: (id: string, signal: AbortSignal) => request<SavedScenario>(`/budget-lab/scenarios/${encodeURIComponent(id)}`, undefined, { signal }),
  clone: (id: number) => post<SavedScenario>(`/scenarios/${id}/clone`, {}),
}

export function budgetFindingLink(finding: Finding) {
  return ["D-01", "D-05"].includes(finding.policy_id)
    ? `/budget-lab?campaign_id=${finding.campaign_id}&finding_id=${finding.id}`
    : null
}

export function units(value: string) {
  if (!/^\d{1,9}(?:\.\d{0,2})?$/.test(value)) return null
  const [whole, decimal = ""] = value.split(".")
  return Number(whole) * 100 + Number(decimal.padEnd(2, "0"))
}

export function unitInput(value: number) {
  return (value / 100).toFixed(2)
}
