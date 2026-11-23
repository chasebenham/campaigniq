import type { Attribution, Decimal, MetricKey, Platform } from "./api"

export const platformNames: Record<Platform, string> = {
  GOOGLE_ADS: "Google Ads",
  META_ADS: "Meta Ads",
}

export const metricNames: Record<MetricKey, string> = {
  spend: "Total spend",
  attributed_purchases: "Attributed purchases",
  attributed_purchase_value: "Attributed purchase value",
  roas: "ROAS",
  impressions: "Impressions",
  clicks: "Clicks",
  ctr: "CTR",
  cpc: "CPC",
  cpa: "CPA",
  cpm: "CPM",
  purchase_cvr: "Purchase CVR",
  attributed_aov: "Attributed AOV",
}

const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 })
const integer = new Intl.NumberFormat("en-US")
const credit = new Intl.NumberFormat("en-US", { maximumFractionDigits: 6 })
const ratio = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 })
const shortDate = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" })
const fullDate = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" })

export function formatMetric(key: MetricKey, value: Decimal | number | null | undefined) {
  if (value == null) return "—"
  if (["spend", "attributed_purchase_value", "cpc", "cpm", "cpa", "attributed_aov"].includes(key)) return money.format(value)
  if (key === "roas") return `${ratio.format(value)}×`
  if (key === "ctr" || key === "purchase_cvr") return `${ratio.format(value)}%`
  if (key === "attributed_purchases") return credit.format(value)
  return integer.format(value)
}

export function formatAxis(key: MetricKey, value: number) {
  if (key === "spend" || key === "attributed_purchase_value" || key === "cpa") return `$${compact.format(value)}`
  if (key === "clicks" || key === "attributed_purchases") return compact.format(value)
  return formatMetric(key, value)
}

export function dateLabel(value: string | number | null, withYear = false) {
  return value === null ? "—" : (withYear ? fullDate : shortDate).format(new Date(value))
}

export function dateRange(first: string | null, last: string | null) {
  if (!first || !last) return "—"
  if (first === last) return dateLabel(first, true)
  return `${dateLabel(first, first.slice(0, 4) !== last.slice(0, 4))} – ${dateLabel(last, true)}`
}

export function formatContext(context: Attribution) {
  const labels: Record<string, string> = {
    PURCHASE: "Purchase", LAST_CLICK: "Last click", DATA_DRIVEN: "Data-driven", LINEAR: "Linear",
    "7D_CLICK": "7-day click", "1D_CLICK": "1-day click", "30D_CLICK": "30-day click",
    "7D_CLICK_1D_VIEW": "7-day click / 1-day view", INTERACTION_DATE: "Interaction date",
    CONVERSION_DATE: "Conversion date", UNKNOWN: "Unknown",
  }
  return [context.conversion_action, context.attribution_method, context.attribution_window, context.date_basis]
    .map((value) => labels[value] ?? value).join(" · ")
}
