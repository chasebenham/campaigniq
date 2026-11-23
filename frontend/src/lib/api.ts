export type Platform = "GOOGLE_ADS" | "META_ADS"
export type CampaignStatus = "ACTIVE" | "PAUSED" | "COMPLETED"
export type Decimal = Intl.StringNumericLiteral
export type MetricKey = keyof Metrics

export interface Metrics {
  impressions: number | Decimal
  clicks: number | Decimal
  spend: Decimal
  attributed_purchases: Decimal | null
  attributed_purchase_value: Decimal | null
  ctr: Decimal | null
  cpc: Decimal | null
  cpm: Decimal | null
  purchase_cvr: Decimal | null
  cpa: Decimal | null
  roas: Decimal | null
  attributed_aov: Decimal | null
}

export interface Attribution {
  conversion_action: string
  attribution_method: string
  attribution_window: string
  date_basis: string
}

export interface Report {
  metrics: Metrics | null
  first_date: string | null
  last_date: string | null
  latest_import_at: string | null
  record_count: number
  fictional_record_count: number
  observed_days: number
  attribution_contexts: Attribution[]
  conversion_status: "available" | "incompatible" | "unavailable" | "empty"
  platform_attributed_overlap: boolean
}

export interface PlatformReport extends Report { platform: Platform }
export interface TrendPoint { date: string; metrics: Metrics }
export interface TrendReport { items: TrendPoint[]; first_date: string | null; last_date: string | null }

export interface CampaignOption {
  id: number
  platform: Platform
  campaign_name: string
}

export interface Campaign extends CampaignOption {
  external_campaign_id: string
  objective: string
  status: CampaignStatus
  target_cpa: Decimal | null
  target_roas: Decimal | null
  currency: string
  start_date: string
  end_date: string | null
  report: Report
  missing_days: number | null
  cpa_target_status: "met" | "missed" | null
  roas_target_status: "met" | "missed" | null
}

export interface CampaignPerformance extends Campaign { trends: TrendReport }
export interface Page<T> { items: T[]; page: number; page_size: number; total: number }
export type Filters = { start_date?: string; end_date?: string; platform?: string; campaign_id?: string }

export interface ImportIssue {
  row_number: number
  field_name: string | null
  error_code: string
  error_message: string
}

export interface PreviewRow {
  row_number: number
  status: "valid" | "duplicate" | "rejected"
  values: Record<string, string>
}

export interface ImportPreview {
  token: string
  total_rows: number
  valid_rows: number
  rejected_rows: number
  duplicate_rows: number
  issue_count: number
  error_counts: Record<string, number>
  rows: PreviewRow[]
  issues: ImportIssue[]
}

export interface ImportRecord {
  id: number
  filename: string
  source_platform: Platform | null
  imported_at: string
  total_rows: number
  valid_rows: number
  rejected_rows: number
  duplicate_rows: number
  import_status: "COMPLETED" | "COMPLETED_WITH_ERRORS" | "REJECTED" | "NO_NEW_ROWS"
  validation_summary: { issue_count?: number; error_counts: Record<string, number> }
  source_type: "SYNTHETIC_SEED" | "CSV_UPLOAD"
}

export interface ImportDetails extends ImportRecord { issues: Page<ImportIssue> }

export class ApiError extends Error {
  constructor(message: string, public readonly code: string) { super(message) }
}

type Params = Record<string, string | number | undefined>

async function request<T>(path: string, params?: Params, init?: RequestInit): Promise<T> {
  const query = new URLSearchParams()
  Object.entries(params ?? {}).forEach(([name, value]) => {
    if (value !== undefined && value !== "") query.set(name, String(value))
  })
  const suffix = query.size ? `?${query}` : ""
  const response = await fetch(`/api/v1${path}${suffix}`, init)
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new ApiError(body?.error?.message ?? `The server returned HTTP ${response.status}.`, body?.error?.code ?? "HTTP_ERROR")
  }
  return response.json() as Promise<T>
}

export async function getCampaignOptions(signal: AbortSignal) {
  const size = 100
  const first = await request<Page<CampaignOption>>("/campaign-options", { page_size: size }, { signal })
  const options = [...first.items]
  for (let page = 2; page <= Math.ceil(first.total / size); page++) {
    const next = await request<Page<CampaignOption>>("/campaign-options", { page, page_size: size }, { signal })
    options.push(...next.items)
  }
  return options
}

export const api = {
  overview: (filters: Filters, signal: AbortSignal) => request<Report>("/analytics/overview", filters, { signal }),
  trends: (filters: Filters, signal: AbortSignal) => request<TrendReport>("/analytics/trends", filters, { signal }),
  platforms: (filters: Filters, signal: AbortSignal) => request<PlatformReport[]>("/analytics/platforms", filters, { signal }),
  campaigns: (params: Params, signal: AbortSignal) => request<Page<Campaign>>("/campaigns", params, { signal }),
  campaign: (id: string, filters: Filters, signal: AbortSignal) => request<CampaignPerformance>(`/campaigns/${id}/performance`, filters, { signal }),
  imports: (page: number, signal: AbortSignal) => request<Page<ImportRecord>>("/imports", { page }, { signal }),
  importDetails: (id: number, page: number, signal: AbortSignal) => request<ImportDetails>(`/imports/${id}`, { page }, { signal }),
  preview: (file: File) => upload<ImportPreview>("/imports/preview", file),
  commit: (file: File, token: string) => upload<ImportRecord>("/imports/commit", file, token),
}

function upload<T>(path: string, file: File, token?: string) {
  const form = new FormData()
  form.append("file", file)
  if (token) form.append("preview_token", token)
  return request<T>(path, undefined, { method: "POST", body: form })
}
