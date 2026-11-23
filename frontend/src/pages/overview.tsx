import { useQuery } from "@tanstack/react-query"
import { Link } from "react-router"

import { CampaignTable } from "@/components/campaign-table"
import { FilterBar, useReportFilters } from "@/components/filters"
import { MetricCards } from "@/components/metrics"
import { ReportChart } from "@/components/report-chart"
import { AttributionNotice, Empty, ErrorPanel, Loading, PageHeading, PanelHeading, PlatformBadge, ReportingPeriod } from "@/components/shared"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { api, getCampaignOptions, type PlatformReport } from "@/lib/api"
import { formatContext, formatMetric } from "@/lib/presentation"

export function Overview() {
  const controls = useReportFilters()
  const { filters, invalid } = controls
  const options = useQuery({ queryKey: ["campaign-options"], queryFn: ({ signal }) => getCampaignOptions(signal) })
  const report = useQuery({
    queryKey: ["performance", "overview", filters],
    enabled: !invalid,
    queryFn: async ({ signal }) => {
      const [overview, trend, platforms, campaigns] = await Promise.all([
        api.overview(filters, signal),
        api.trends(filters, signal),
        api.platforms(filters, signal),
        api.campaigns({ ...filters, sort: "spend", direction: "desc", page_size: 5 }, signal),
      ])
      return { overview, trend, platforms, campaigns }
    },
  })
  const data = report.data
  const overview = data?.overview

  return <>
    <PageHeading title="Performance overview" description="Track paid acquisition across Google Ads and Meta Ads.">
      {Boolean(overview?.fictional_record_count) && <Badge className="fictional-badge">
        <span className="badge-dot" aria-hidden="true" />
        {overview?.fictional_record_count === overview?.record_count ? "Fictional data" : "Includes fictional data"}
      </Badge>}
    </PageHeading>
    <FilterBar {...controls} campaigns={options.data ?? []} optionsUnavailable={options.isError}
      reset={() => controls.change({ start_date: "", end_date: "", platform: "", campaign_id: "" })} />
    {options.isError && <p className="support-text" role="status">Campaign choices could not load. Date and platform filters are available.</p>}
    {!invalid && (report.isPending ? <Loading /> : report.isError ? <ErrorPanel error={report.error} retry={() => void report.refetch()} /> :
      data && overview?.metrics ? <>
        <ReportingPeriod report={overview} />
        <MetricCards metrics={overview.metrics} />
        <div className="overview-visuals">
          <ReportChart items={data.trend.items} />
          <PlatformComparison rows={data.platforms} />
        </div>
        <AttributionNotice report={overview} />
        <Card className="table-card">
          <PanelHeading title="Campaign performance" description="Top campaigns by spend in this selection.">
            <Link className="text-link" to={`/campaigns${controls.params.size ? `?${controls.params}` : ""}`}>View all campaigns</Link>
          </PanelHeading>
          <CampaignTable items={data.campaigns.items} filters={filters} compact />
        </Card>
      </> : <Empty title="No performance data" description="Adjust the report filters or import a standardized CSV to get started." />)}
  </>
}

function PlatformComparison({ rows }: { rows: PlatformReport[] }) {
  return <Card className="platform-card">
    <PanelHeading title="Platform comparison" description="Spend and attributed efficiency by platform." />
    <div className="platform-reports">
      {rows.map((row) => <div className="platform-report" key={row.platform}>
        <PlatformBadge platform={row.platform} />
        <dl>
          <div><dt>Spend</dt><dd>{formatMetric("spend", row.metrics?.spend)}</dd></div>
          <div><dt>CPA</dt><dd>{formatMetric("cpa", row.metrics?.cpa)}</dd></div>
          <div><dt>ROAS</dt><dd>{formatMetric("roas", row.metrics?.roas)}</dd></div>
        </dl>
        <p>{row.conversion_status === "available" ? formatContext(row.attribution_contexts[0]) : "Conversion definitions differ or are unknown."}</p>
      </div>)}
    </div>
  </Card>
}
