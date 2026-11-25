import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Download, FilePlus, Info, Sparkles } from "lucide-react"
import { Link, useParams } from "react-router"

import { BriefDocument } from "@/components/brief-document"
import { Empty, ErrorPanel, Loading, PageHeading, Pagination, PanelHeading } from "@/components/shared"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { ai } from "@/lib/ai"
import { briefs, type VersionView } from "@/lib/briefs"
import { dateLabel, dateRange } from "@/lib/presentation"

function ExportLink({ id, version, compact = false }: { id: number; version: number; compact?: boolean }) {
  return <a className={compact ? "text-link" : "brief-export"} href={briefs.pdf(id, version)}
    aria-label={`Export PDF for version ${version}`} download>{!compact && <Download size={16} aria-hidden="true" />}Export PDF</a>
}

export function StrategyBriefs() {
  const [page, setPage] = useState(1)
  const data = useQuery({ queryKey: ["briefs", "list", page], queryFn: ({ signal }) => briefs.list(page, signal) })
  return <>
    <PageHeading title="Strategy Briefs" description="Turn verified campaign evidence into a versioned report for leadership.">
      <Link className="brief-create" to="/strategy-briefs/new"><FilePlus size={17} aria-hidden="true" />Create Strategy Brief</Link>
    </PageHeading>
    {data.isPending ? <Loading label="Loading strategy briefs…" /> :
      data.isError ? <ErrorPanel error={data.error} retry={() => void data.refetch()} /> :
      !data.data.items.length && page === 1 ? <Empty title="No strategy briefs yet"
        description="Create a brief with a reporting period, selected evidence, and recommendations for leadership." /> :
      <Card className="table-card">
        <PanelHeading title="Saved briefs" />
        <div className="table-scroll" role="region" tabIndex={0} aria-label="Saved strategy briefs">
          <table className="data-table">
            <thead><tr>{["Report", "Reporting period", "Last updated", "Version", "Status", "Data freshness", "PDF"].map(label =>
              <th scope="col" key={label}>{label}</th>)}</tr></thead>
            <tbody>{data.data.items.map(row => <tr key={row.id}>
              <th scope="row"><Link className="text-link" to={`/strategy-briefs/${row.id}`}>{row.title}</Link></th>
              <td>{dateRange(row.period.start, row.period.end)}</td><td>{dateLabel(row.updated_at, true)}</td>
              <td>v{row.current_version}</td><td>Saved</td>
              <td className={row.freshness === "STALE" ? "budget-blocked" : ""}>{row.freshness === "STALE" ? "Evidence changed" : "Current"}</td>
              <td><ExportLink id={row.id} version={row.current_version} compact /></td>
            </tr>)}</tbody>
          </table>
        </div>
        <Pagination data={data.data} label="Brief pages" onChange={setPage} />
      </Card>}
  </>
}

export function SavedBrief() {
  const { briefId = "", version } = useParams()
  const report = useQuery({
    queryKey: version ? ["briefs", "report", briefId, version] : ["briefs", "report", briefId],
    queryFn: ({ signal }) => briefs.read(briefId, version, signal),
    refetchInterval: query => query.state.data?.generation?.status === "PENDING" ? 1800 : false,
  })
  const row = report.data
  return <>
    <Link className="text-link parent-link" to="/strategy-briefs">Strategy Briefs</Link>
    <PageHeading title={row?.title ?? "Strategy brief"} description={row ? `Saved version ${row.version} · ${dateRange(row.period.start, row.period.end)}` : "Open the saved executive snapshot."}>
      {row && <div className="brief-wrap">
        {row.version === row.current_version ?
          <Link className="text-link" to={`/strategy-briefs/${briefId}/edit`}>Revise brief</Link> :
          <Link className="text-link" to={`/strategy-briefs/${briefId}`}>Open latest version</Link>}
        <ExportLink id={row.brief_id} version={row.version} />
      </div>}
    </PageHeading>
    {report.isPending ? <Loading label="Loading the saved report…" /> :
      report.isError ? <ErrorPanel error={report.error} retry={() => void report.refetch()} /> : <>
        {report.data.freshness === "STALE" && <aside className="attribution-notice" role="status">
          <Info size={18} aria-hidden="true" /><div><strong>Source evidence has changed</strong>
            <p>This saved report and its PDF retain the original evidence. Refresh evidence in a new version to review changes.</p></div>
        </aside>}
        <BriefDocument document={report.data.document} version={report.data.version} />
        <ExecutiveSummary key={`${briefId}-${report.data.version}`} row={report.data} />
        <VersionHistory key={briefId} id={briefId} current={report.data.version} />
      </>}
  </>
}

function ExecutiveSummary({ row }: { row: VersionView }) {
  const id = String(row.brief_id)
  const valid = row.version === row.current_version && row.freshness !== "STALE"
  const cache = useQueryClient()
  const availability = useQuery({ queryKey: ["ai", "availability"], enabled: valid, queryFn: ({ signal }) => ai.availability(signal) })
  const generate = useMutation({
    mutationFn: () => briefs.generate(id, row.version),
    onSettled: () => cache.invalidateQueries({ queryKey: ["briefs", "report", id] }),
  })
  const proposal = row.generation
  const running = generate.isPending || proposal?.status === "PENDING"
  return <Card>
    <PanelHeading title="Optional AI executive summary"
      description="Request a qualitative proposal grounded in this version’s sources. Apply it to a new version if you choose.">
      {valid && availability.data?.enabled && proposal?.status !== "COMPLETED" &&
        <Button onClick={() => generate.mutate()} disabled={running}><Sparkles size={17} aria-hidden="true" />
          {running ? "Generating summary…" : "Generate Executive Summary with AI"}</Button>}
    </PanelHeading>
    <div className="brief-form-row brief-ai">
      {valid && availability.isError && <ErrorPanel error={availability.error} retry={() => void availability.refetch()} />}
      {valid && availability.data && !availability.data.enabled && <p className="support-text">AI is unavailable. You can add an executive summary in a revision.</p>}
      {!valid && <p className="support-text">Generation requires the latest version with current evidence.</p>}
      {running && <p role="status">Generating from the saved evidence…</p>}
      {generate.error && <ErrorPanel error={generate.error} />}
      {proposal?.error && !generate.error && <p className="support-text" role="status">{proposal.error}</p>}
      {proposal?.status === "COMPLETED" && proposal.text && <div className="brief-proposal">
        <p><strong>AI proposal</strong> · {proposal.model}</p><p>{proposal.text}</p>
        <p className="support-text">Evidence references · {proposal.references.join(", ")}</p>
        {row.version === row.current_version && <Link className="text-link" to={`/strategy-briefs/${id}/edit?summary_attempt=${proposal.id}`}>Use proposal in a revision</Link>}
      </div>}
    </div>
  </Card>
}

function VersionHistory({ id, current }: { id: string; current: number }) {
  const [page, setPage] = useState(1)
  const data = useQuery({ queryKey: ["briefs", "versions", id, page], queryFn: ({ signal }) => briefs.versions(id, page, signal) })
  return <Card className="table-card">
    <PanelHeading title="Version history" description="Each version retains its saved evidence, commentary, and export." />
    {data.isPending ? <Loading label="Loading versions…" /> :
      data.isError ? <ErrorPanel error={data.error} retry={() => void data.refetch()} /> : <>
        <div className="table-scroll"><table className="data-table" aria-label="Strategy brief version history">
          <thead><tr><th scope="col">Version</th><th scope="col">Title</th><th scope="col">Saved</th><th scope="col">PDF</th></tr></thead>
          <tbody>{data.data.items.map(item => <tr key={item.version}>
            <th scope="row"><Link aria-current={current === item.version ? "page" : undefined} className="text-link"
              to={`/strategy-briefs/${id}/versions/${item.version}`}>Version {item.version}</Link></th>
            <td>{item.title}</td><td>{dateLabel(item.generated_at, true)}</td><td><ExportLink compact id={Number(id)} version={item.version} /></td>
          </tr>)}</tbody>
        </table></div>
        <Pagination data={data.data} label="Version pages" onChange={setPage} />
      </>}
  </Card>
}
