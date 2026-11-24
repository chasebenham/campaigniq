import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CheckCircle2, CircleAlert, FileSpreadsheet, UploadCloud } from "lucide-react"

import { Empty, ErrorPanel, Loading, PageHeading, Pagination, PanelHeading, PlatformBadge } from "@/components/shared"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { api, ApiError, type ImportIssue, type ImportPreview, type ImportRecord } from "@/lib/api"
import { dateLabel } from "@/lib/presentation"

const statusLabels: Record<ImportRecord["import_status"], string> = {
  COMPLETED: "Completed", COMPLETED_WITH_ERRORS: "Completed with errors", REJECTED: "Rejected", NO_NEW_ROWS: "No new rows",
}

export function Imports() {
  const queryClient = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [record, setRecord] = useState<ImportRecord | null>(null)
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<number | null>(null)
  const [issuePage, setIssuePage] = useState(1)
  const history = useQuery({ queryKey: ["imports", page], queryFn: ({ signal }) => api.imports(page, signal) })
  const details = useQuery({
    queryKey: ["import-details", selected, issuePage], enabled: selected !== null,
    queryFn: ({ signal }) => api.importDetails(selected!, issuePage, signal),
  })
  const parse = useMutation({
    mutationFn: api.preview,
    onSuccess: (response) => setPreview(response),
  })
  const commit = useMutation({
    mutationFn: ({ selectedFile, token }: { selectedFile: File; token: string }) => api.commit(selectedFile, token),
    onError: (error) => {
      if (error instanceof ApiError && error.code === "STALE_PREVIEW") setPreview(null)
    },
    onSuccess: async (response) => {
      setRecord(response)
      setPreview(null)
      setPage(1)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["imports"] }),
        queryClient.invalidateQueries({ queryKey: ["performance"] }),
        queryClient.invalidateQueries({ queryKey: ["campaign-options"] }),
        queryClient.invalidateQueries({ queryKey: ["detection"] }),
        queryClient.invalidateQueries({ queryKey: ["ai", "history"] }),
      ])
    },
  })
  const busy = parse.isPending || commit.isPending
  const operationError = parse.error || commit.error

  function selectFile(selection: File | null) {
    setFile(selection)
    setPreview(null)
    setRecord(null)
    parse.reset()
    commit.reset()
  }

  function previewFile() {
    if (!file) return
    setPreview(null)
    setRecord(null)
    commit.reset()
    parse.mutate(file)
  }

  return <>
    <PageHeading title="Data imports" description="Validate standardized advertising CSVs and review every import." />
    <Card className="upload-card">
      <PanelHeading title="Import a CSV" description="Use the CampaignIQ schema for Google Ads and Meta Ads. CSV files may contain up to 20,000 rows and 5 MiB.">
        <a className="text-link" href={`${import.meta.env.BASE_URL}campaigniq-sample.csv`} download>Download fictional sample CSV</a>
      </PanelHeading>
      <div className="file-zone">
        <span className="metric-icon tone-blue"><FileSpreadsheet size={21} /></span>
        <div>
          <label htmlFor="csv-file">Choose a CSV file</label>
          <input id="csv-file" type="file" accept=".csv,text/csv" onChange={(e) => selectFile(e.target.files?.[0] ?? null)} disabled={busy} />
        </div>
        <Button onClick={previewFile} disabled={!file || busy}><UploadCloud size={17} />{parse.isPending ? "Validating…" : "Preview CSV"}</Button>
      </div>
      {operationError && <div role="alert" className="import-error">{operationError.message}</div>}
      {record && <div role="status" className={`import-result ${record.rejected_rows ? "import-result-warning" : ""}`}>
        {record.rejected_rows ? <CircleAlert size={18} /> : <CheckCircle2 size={18} />}
        <p><strong>{statusLabels[record.import_status]}.</strong> {record.valid_rows} imported · {record.duplicate_rows} duplicate · {record.rejected_rows} rejected.</p>
      </div>}
    </Card>

    {preview && <Card className="table-card preview-card">
      <PanelHeading title="CSV preview" description={`Showing ${preview.rows.length} of ${preview.total_rows} data rows.`}>
        <Button disabled={!file || busy} onClick={() => {
          if (file) commit.mutate({ selectedFile: file, token: preview.token })
        }}>{commit.isPending ? "Saving…" : preview.valid_rows > 0 ? `Import ${preview.valid_rows} ${preview.valid_rows === 1 ? "row" : "rows"}` : "Save validation result"}</Button>
      </PanelHeading>
      <div className="import-counts">
        <Badge className="status-active">{preview.valid_rows} ready</Badge>
        <Badge className="status-completed">{preview.duplicate_rows} duplicate</Badge>
        <Badge className="status-paused">{preview.rejected_rows} rejected</Badge>
      </div>
      {preview.rejected_rows > 0 && <p className="table-note">Rejected rows will be recorded in import history. Only ready rows will add campaign performance.</p>}
      <div className="table-scroll"><table className="data-table" aria-label="CSV preview">
        <thead><tr>{["Line", "Date", "Campaign", "Platform", "Impressions", "Clicks", "Spend", "Purchase credit", "Purchase value", "Definition", "Currency", "Result"].map((title) => <th key={title} scope="col">{title}</th>)}</tr></thead>
        <tbody>{preview.rows.map((row) => <tr key={row.row_number}>
          <td>{row.row_number}</td><td>{row.values.date || "—"}</td><td>{row.values.campaign_name || row.values.campaign_id || "—"}</td>
          <td>{row.values.platform || "—"}</td><td>{row.values.impressions || "—"}</td><td>{row.values.clicks || "—"}</td>
          <td>{row.values.spend || "—"}</td><td>{row.values.attributed_purchases || "—"}</td><td>{row.values.attributed_purchase_value || "—"}</td>
          <td>{[row.values.conversion_action, row.values.attribution_method, row.values.attribution_window, row.values.date_basis].filter(Boolean).join(" · ") || "—"}</td>
          <td>{row.values.currency || "—"}</td><td>{row.status}</td>
        </tr>)}</tbody>
      </table></div>
      {preview.issues.length > 0 && <>
        <PanelHeading title="Validation issues" description={`Showing ${preview.issues.length} of ${preview.issue_count} issues.`} />
        <IssueTable issues={preview.issues} />
      </>}
    </Card>}

    <Card className="table-card">
      <PanelHeading title="Import history" description="Imported rows, duplicates, and rejected records by file." />
      {history.isPending ? <Loading label="Loading import history…" /> : history.isError ?
        <ErrorPanel error={history.error} retry={() => void history.refetch()} /> : history.data.total === 0 ?
        <Empty title="No imports yet" description="Select a standardized CSV to create your first import." /> : <>
          <div className="table-scroll"><table className="data-table" aria-label="Import history">
            <thead><tr>{["File", "Platform", "Imported", "Added", "Duplicates", "Rejected", "Status"].map((title) => <th key={title} scope="col">{title}</th>)}</tr></thead>
            <tbody>{history.data.items.map((entry) => <tr key={entry.id}>
              <th scope="row"><button type="button" className="text-link" aria-expanded={selected === entry.id} onClick={() => {
                setSelected(selected === entry.id ? null : entry.id)
                setIssuePage(1)
              }}>{entry.filename}</button>
                <small className="table-secondary">{entry.source_type === "SYNTHETIC_SEED" ? "Fictional seed" : "CSV upload"}</small>
              </th>
              <td>{entry.source_platform ? <PlatformBadge platform={entry.source_platform} /> : "Mixed / unspecified"}</td>
              <td>{dateLabel(entry.imported_at, true)}</td><td>{entry.valid_rows.toLocaleString("en-US")}</td>
              <td>{entry.duplicate_rows}</td><td>{entry.rejected_rows}</td><td>{statusLabels[entry.import_status]}</td>
            </tr>)}</tbody>
          </table></div>
          <Pagination data={history.data} onChange={setPage} label="Import history pages" />
        </>}
    </Card>

    {selected !== null && <Card className="table-card">
      <PanelHeading title="Import validation details" description={details.data?.filename} />
      {details.isPending ? <Loading label="Loading validation details…" /> : details.isError ?
        <ErrorPanel error={details.error} retry={() => void details.refetch()} /> :
        details.data.issues.total === 0 ? <p className="panel-empty">This import has no rejected-row issues.</p> : <>
          <IssueTable issues={details.data.issues.items} />
          <Pagination data={details.data.issues} onChange={setIssuePage} label="Validation issue pages" />
        </>}
    </Card>}
  </>
}

function IssueTable({ issues }: { issues: ImportIssue[] }) {
  return <div className="table-scroll"><table className="data-table" aria-label="Validation issues">
    <thead><tr><th scope="col">Line</th><th scope="col">Field</th><th scope="col">Issue</th></tr></thead>
    <tbody>{issues.map((issue) => <tr key={`${issue.row_number}-${issue.field_name}-${issue.error_code}`}>
      <td>{issue.row_number}</td><td>{issue.field_name ?? "Row"}</td><td>{issue.error_message}</td>
    </tr>)}</tbody>
  </table></div>
}
