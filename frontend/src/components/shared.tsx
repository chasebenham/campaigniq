import type { ReactNode } from "react"
import { BarChart3, CalendarDays, CircleAlert, Info, LoaderCircle } from "lucide-react"

import type { Page, Platform, Report } from "@/lib/api"
import { dateLabel, dateRange, formatContext, platformNames } from "@/lib/presentation"
import { Badge } from "./ui/badge"
import { Button } from "./ui/button"
import { Card } from "./ui/card"

export function PageHeading({ title, description, children }: { title: string; description: string; children?: ReactNode }) {
  return <div className="page-heading"><div><h1>{title}</h1><p>{description}</p></div>{children}</div>
}

export function Loading({ label = "Loading performance data…" }: { label?: string }) {
  return <Card className="state-panel" role="status"><LoaderCircle className="animate-spin" size={23} /><p>{label}</p></Card>
}

export function ErrorPanel({ error, retry }: { error: Error; retry?: () => void }) {
  return <Card className="state-panel" role="alert">
    <CircleAlert size={24} /><strong>Unable to load data</strong><p>{error.message}</p>
    {retry && <Button variant="outline" onClick={retry}>Try again</Button>}
  </Card>
}

export function Empty({ title, description }: { title: string; description: string }) {
  return <Card className="state-panel"><BarChart3 size={24} /><strong>{title}</strong><p>{description}</p></Card>
}

export function PanelHeading({ title, description, children }: { title: string; description?: string; children?: ReactNode }) {
  return <div className="panel-heading"><div><h2>{title}</h2>{description && <p>{description}</p>}</div>{children}</div>
}

export function PlatformBadge({ platform }: { platform: Platform }) {
  return <Badge className={platform === "GOOGLE_ADS" ? "platform-google" : "platform-meta"}>
    <span className="badge-dot" aria-hidden="true" />{platformNames[platform]}
  </Badge>
}

export function AttributionNotice({ report }: { report: Report }) {
  if (!report.record_count) return null
  const mixed = report.conversion_status === "incompatible" || report.conversion_status === "unavailable"
  return (
    <aside className="attribution-notice" aria-label="Attribution and data source">
      <Info size={18} aria-hidden="true" />
      <div>
        <strong>{mixed ? "Conversion metrics unavailable for this selection" : "About platform attribution"}</strong>
        <p>
          {mixed && "The selected records contain different or unknown reporting definitions. Choose a campaign with a single supported definition to see its conversion metrics. "}
          {report.platform_attributed_overlap && "Platform-attributed purchase credit may overlap across Google Ads and Meta Ads. "}
          ROAS measures attributed purchase value per dollar of ad spend. Profit and incremental revenue require separate analysis.
        </p>
        {report.attribution_contexts.length > 0 && (
          <ul className="context-list">{report.attribution_contexts.map((context) => (
            <li key={formatContext(context)}>{formatContext(context)}</li>
          ))}</ul>
        )}
      </div>
    </aside>
  )
}

export function ReportingPeriod({ report }: { report: Report }) {
  return <div className="report-period">
    <span><CalendarDays size={16} aria-hidden="true" />{dateRange(report.first_date, report.last_date)}
      <span className="dot-divider" aria-hidden="true">·</span> {report.observed_days} reporting {report.observed_days === 1 ? "day" : "days"}
    </span>
    {report.latest_import_at && <span>Latest import {dateLabel(report.latest_import_at, true)}</span>}
  </div>
}

export function Pagination<T>({ data, onChange, label }: { data: Page<T>; onChange: (page: number) => void; label: string }) {
  if (data.total <= data.page_size && data.page === 1) return null
  const max = Math.max(1, Math.ceil(data.total / data.page_size))
  return <nav className="pagination" aria-label={label}>
    <span>Page {data.page} of {max} · {data.total} total</span>
    <div>
      <Button variant="outline" onClick={() => onChange(data.page - 1)} disabled={data.page <= 1}>Previous</Button>
      <Button variant="outline" onClick={() => onChange(data.page + 1)} disabled={data.page >= max}>Next</Button>
    </div>
  </nav>
}
