import { useQuery } from "@tanstack/react-query"
import { CircleAlert } from "lucide-react"
import { Link, useParams } from "react-router"

import { CampaignTable, StatusBadge, type CampaignSort } from "@/components/campaign-table"
import { FilterBar, SelectField, useReportFilters } from "@/components/filters"
import { MetricCards } from "@/components/metrics"
import { ReportChart } from "@/components/report-chart"
import { AttributionNotice, Empty, ErrorPanel, Loading, PageHeading, Pagination, PanelHeading, PlatformBadge, ReportingPeriod } from "@/components/shared"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { api, getCampaignOptions, type CampaignPerformance } from "@/lib/api"
import { dateLabel, formatMetric } from "@/lib/presentation"

export function Campaigns() {
  const controls = useReportFilters()
  const { filters, invalid, params, change } = controls
  const sort = params.get("sort") || "spend"
  const direction = params.get("direction") === "asc" ? "asc" : "desc"
  const page = Number(params.get("page")) || 1
  const status = params.get("status") || ""
  const options = useQuery({ queryKey: ["campaign-options"], queryFn: ({ signal }) => getCampaignOptions(signal) })
  const result = useQuery({
    queryKey: ["performance", "campaigns", filters, sort, direction, status, page],
    enabled: !invalid,
    queryFn: ({ signal }) => api.campaigns({ ...filters, sort, direction, status, page }, signal),
  })

  function sortBy(key: CampaignSort) {
    const next = sort === key ? direction === "asc" ? "desc" : "asc" :
      ["campaign_name", "platform", "status"].includes(key) ? "asc" : "desc"
    change({ sort: key, direction: next, page: "" })
  }

  return <>
    <PageHeading title="Campaigns" description="Compare campaign performance and review reported efficiency against targets." />
    <FilterBar {...controls} campaigns={options.data ?? []} optionsUnavailable={options.isError}
      reset={() => change({ start_date: "", end_date: "", platform: "", campaign_id: "", status: "", page: "" })}>
      <SelectField label="Status" value={status} onChange={(value) => change({ status: value, page: "" })}>
        <option value="">All statuses</option><option value="ACTIVE">Active</option>
        <option value="PAUSED">Paused</option><option value="COMPLETED">Completed</option>
      </SelectField>
    </FilterBar>
    {!invalid && (result.isPending ? <Loading label="Loading campaigns…" /> :
      result.isError ? <ErrorPanel error={result.error} retry={() => void result.refetch()} /> :
      result.data.total === 0 ? <Empty title="No campaigns match" description="Change the filters or import campaign data." /> :
      <Card className="table-card">
        <PanelHeading title="Campaign performance" description="KPI values reflect the selected reporting period." />
        {result.data.items.some((item) => item.report.fictional_record_count > 0) &&
          <p className="table-note">Includes fictional Northstar Outfitters seed data.</p>}
        {result.data.items.length === 0 ? <p className="panel-empty">There are no campaigns on this page.</p> :
          <CampaignTable items={result.data.items} filters={filters} sort={sort} direction={direction} onSort={sortBy} />}
        <Pagination data={result.data} onChange={(value) => change({ page: String(value) })} label="Campaign pages" />
      </Card>)}
  </>
}

export function CampaignDetail() {
  const id = useParams().campaignId ?? ""
  const controls = useReportFilters(["start_date", "end_date"])
  const { filters, invalid } = controls
  const result = useQuery({
    queryKey: ["performance", "campaign", id, filters],
    enabled: Boolean(id) && !invalid,
    queryFn: ({ signal }) => api.campaign(id, filters, signal),
  })
  const campaign = result.data
  const report = campaign?.report
  const listParams = new URLSearchParams()
  if (filters.start_date) listParams.set("start_date", filters.start_date)
  if (filters.end_date) listParams.set("end_date", filters.end_date)

  return <>
    <Link to={`/campaigns${listParams.size ? `?${listParams}` : ""}`} className="text-link parent-link">Campaigns</Link>
    <PageHeading title={campaign?.campaign_name ?? "Campaign detail"} description="Daily performance, campaign targets, and reporting definitions.">
      {campaign && <div className="heading-badges">
        <PlatformBadge platform={campaign.platform} /><StatusBadge status={campaign.status} />
        {Boolean(report?.fictional_record_count) && <Badge className="fictional-badge">
          {report?.fictional_record_count === report?.record_count ? "Fictional data" : "Includes fictional data"}
        </Badge>}
      </div>}
    </PageHeading>
    <FilterBar {...controls} dateOnly reset={() => controls.change({ start_date: "", end_date: "" })} />
    {!invalid && (result.isPending ? <Loading label="Loading campaign performance…" /> :
      result.isError ? <ErrorPanel error={result.error} retry={() => void result.refetch()} /> :
      campaign && report && <>
        <Card className="campaign-meta">
          <dl>
            <div><dt>External campaign ID</dt><dd>{campaign.external_campaign_id}</dd></div>
            <div><dt>Objective</dt><dd>{campaign.objective === "PURCHASES" ? "Purchases" : campaign.objective}</dd></div>
            <div><dt>Campaign start</dt><dd>{dateLabel(campaign.start_date, true)}</dd></div>
            <div><dt>Campaign end</dt><dd>{campaign.end_date ? dateLabel(campaign.end_date, true) : "Open"}</dd></div>
          </dl>
        </Card>
        {report.metrics ? <>
          <ReportingPeriod report={report} />
          <MetricCards metrics={report.metrics} full />
          <div className="overview-visuals">
            <ReportChart items={campaign.trends.items} />
            <Targets campaign={campaign} />
          </div>
          {Boolean(campaign.missing_days) && <div className="coverage-note" role="status">
            <CircleAlert size={18} /> <p><strong>Incomplete date coverage.</strong> {campaign.missing_days} expected calendar {campaign.missing_days === 1 ? "day has" : "days have"} no campaign record in this period.</p>
          </div>}
          <AttributionNotice report={report} />
        </> : <Empty title="No performance data" description="This campaign has no records for the selected dates." />}
      </>)}
  </>
}

function Targets({ campaign }: { campaign: CampaignPerformance }) {
  const metrics = campaign.report.metrics
  const targets = [
    { key: "cpa", label: "Cost per purchase", target: campaign.target_cpa, status: campaign.cpa_target_status },
    { key: "roas", label: "Return on ad spend", target: campaign.target_roas, status: campaign.roas_target_status },
  ] as const

  return <Card className="platform-card">
    <PanelHeading title="Campaign targets" description="Actual versus target for this period." />
    <div className="platform-reports">
      {targets.map(({ key, label, target, status }) => <div className="platform-report" key={key}>
        <div className="target-title"><h3>{label}</h3>{status && <Badge className={status === "met" ? "status-active" : "status-paused"}>{status === "met" ? "Target met" : "Target missed"}</Badge>}</div>
        <dl><div><dt>Actual</dt><dd>{formatMetric(key, metrics?.[key])}</dd></div>
          <div><dt>Target</dt><dd>{formatMetric(key, target)}</dd></div></dl>
        {target === null && <p>No target recorded for this campaign.</p>}
      </div>)}
    </div>
  </Card>
}
