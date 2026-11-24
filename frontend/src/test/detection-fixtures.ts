import type { DetectionRun, Finding, PeriodEvidence } from "@/lib/detection"

export const period: PeriodEvidence = {
  start: "2026-11-09", end: "2026-11-15", calendar_days: 7, expected_days: 7,
  observed_days: 7, fictional_days: 7, missing_dates: [], complete: true,
  metrics: { spend: "600.00", clicks: 1000, impressions: 10000, attributed_purchases: "20",
    attributed_purchase_value: "1200", cpa: "30", roas: "2", purchase_cvr: "2", ctr: "10",
    cpc: "0.60", cpm: "60", attributed_aov: "60" },
}

export const sampleFinding: Finding = {
  id: 21, run_id: 3, campaign_id: 2, policy_id: "D-01", policy_version: "1.0.0", category: "PERFORMANCE_RISK",
  severity: "HIGH", summary: "CPA deterioration", classification_reason: "Elevated spend exposure.",
  current_evidence: period, baseline_evidence: { ...period, start: "2026-11-02", end: "2026-11-08" },
  campaign_snapshot: { campaign_name: "Trail Collection Search", platform: "GOOGLE_ADS", objective: "PURCHASES",
    external_campaign_id: "NS-G01", target_cpa: "25", target_roas: "4" },
  thresholds: { cpa_increase_pct: "20" }, observations: { cpa_change_pct: "25" },
  reporting_context: [{ conversion_action: "PURCHASE", attribution_method: "LAST_CLICK",
    attribution_window: "7D_CLICK", date_basis: "INTERACTION_DATE" }],
  evidence_quality: "SUFFICIENT",
  data_quality_flags: [],
  limitations: ["Conversion credit is platform-attributed."],
  created_at: "2026-11-23T18:30:00Z", state: "CURRENT",
}

export const sampleRun: DetectionRun = {
  id: 3, started_at: "2026-11-23T18:29:58Z", finished_at: "2026-11-23T18:30:00Z",
  evaluation_date: "2026-11-23", status: "COMPLETED", state: "CURRENT", policy_version: "1.0.0",
  windows: { current: period, baseline: sampleFinding.baseline_evidence!, history: { start: "2026-10-05", end: "2026-11-01" }, maturation_days: 7 },
  campaign_count: 16, finding_count: 1, suppression_count: 2, errors: [], reused: false,
}

export function page<T>(items: T[]) {
  return { items, page: 1, page_size: 25, total: items.length }
}
