import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react"
import { Link } from "react-router"

import type { Campaign, Filters } from "@/lib/api"
import { dateRange, formatMetric } from "@/lib/presentation"
import { PlatformBadge } from "./shared"
import { Badge } from "./ui/badge"

const columns = [
  ["campaign_name", "Campaign"], ["platform", "Platform"], ["status", "Status"],
  ["spend", "Spend"], ["clicks", "Clicks"], ["attributed_purchases", "Attributed purchases"],
  ["cpa", "CPA"], ["roas", "ROAS"], ["target_cpa", "Target CPA"], ["target_roas", "Target ROAS"],
  ["last_date", "Reporting period"],
] as const

export type CampaignSort = (typeof columns)[number][0]
export type Direction = "asc" | "desc"

export function CampaignTable({ items, filters, sort, direction, onSort, compact = false }: {
  items: Campaign[]; filters: Filters; sort?: string; direction?: Direction;
  onSort?: (key: CampaignSort) => void; compact?: boolean;
}) {
  const detailParams = new URLSearchParams()
  if (filters.start_date) detailParams.set("start_date", filters.start_date)
  if (filters.end_date) detailParams.set("end_date", filters.end_date)
  const suffix = detailParams.size ? `?${detailParams}` : ""
  const visible = compact ? columns.filter(([key]) => !["status", "clicks", "target_cpa", "target_roas", "last_date"].includes(key)) : columns

  return <div className="table-scroll" tabIndex={0} role="region" aria-label="Campaign table">
    <table className={compact ? "data-table data-table-compact" : "data-table"} aria-label="Campaign performance">
      <thead><tr>{visible.map(([key, label]) => {
        const active = sort === key
        const Icon = active ? direction === "asc" ? ArrowUp : ArrowDown : ArrowUpDown
        return <th key={key} scope="col" className={["campaign_name", "platform", "status", "last_date"].includes(key) ? "" : "number-cell"}
          aria-sort={onSort && active ? direction === "asc" ? "ascending" : "descending" : undefined}>
          {onSort ? <button type="button" aria-label={`Sort by ${label}`} onClick={() => onSort(key)}>{label}<Icon size={13} /></button> : label}
        </th>
      })}</tr></thead>
      <tbody>{items.map((campaign) => {
        const { report } = campaign
        const metrics = report.metrics
        return <tr key={campaign.id}>
          <th scope="row"><Link to={`/campaigns/${campaign.id}${suffix}`} className="campaign-link">{campaign.campaign_name}</Link></th>
          <td><PlatformBadge platform={campaign.platform} /></td>
          {!compact && <td><StatusBadge status={campaign.status} /></td>}
          <td className="number-cell">{formatMetric("spend", metrics?.spend)}</td>
          {!compact && <td className="number-cell">{formatMetric("clicks", metrics?.clicks)}</td>}
          <td className="number-cell">{formatMetric("attributed_purchases", metrics?.attributed_purchases)}</td>
          <td className="number-cell">{formatMetric("cpa", metrics?.cpa)}</td>
          <td className="number-cell">{formatMetric("roas", metrics?.roas)}</td>
          {!compact && <>
            <td className="number-cell">{formatMetric("cpa", campaign.target_cpa)}</td>
            <td className="number-cell">{formatMetric("roas", campaign.target_roas)}</td>
            <td>{dateRange(report.first_date, report.last_date)}</td>
          </>}
        </tr>
      })}</tbody>
    </table>
  </div>
}

export function StatusBadge({ status }: { status: Campaign["status"] }) {
  const label = { ACTIVE: "Active", PAUSED: "Paused", COMPLETED: "Completed" }[status]
  return <Badge className={`status-${status.toLowerCase()}`}><span className="badge-dot" aria-hidden="true" />{label}</Badge>
}
