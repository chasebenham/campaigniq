import type { Block, Document, SourceKind } from "@/lib/briefs"
import { dateRange } from "@/lib/presentation"
import { Card } from "./ui/card"

const labels: Record<SourceKind, string> = {
  verified: "Verified evidence", ai: "AI interpretation", modeled: "Hypothetical", management: "Management",
}
const timestamp = new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" })

function Content({ block }: { block: Block }) {
  return <div className="brief-block">
    {(block.title || block.source) && <header className="brief-block-heading">
      {block.title && <h3>{block.title}</h3>}
      {block.source && <span className={`brief-source brief-source-${block.source}`}>{labels[block.source]}</span>}
    </header>}
    {block.paragraphs.map((text, index) => <p key={index}>{text}</p>)}
    {block.tables.map((table, index) => <div key={index} className="brief-table">
      <div className="table-scroll" tabIndex={0} role="region" aria-label={table.headers[0] + " table"}>
        <table className="data-table">
          <thead><tr>{table.headers.map(label => <th key={label} scope="col">{label}</th>)}</tr></thead>
          <tbody>{table.rows.map((row, index) => <tr key={index}>
            <th scope="row">{row[0]}</th>{row.slice(1).map((cell, i) => <td key={i}>{cell}</td>)}
          </tr>)}</tbody>
        </table>
      </div>
      {table.caption && <p className="brief-caption">{table.caption}</p>}
    </div>)}
    {!!block.bullets.length && <ul>{block.bullets.map((text, index) => <li key={index}>{text}</li>)}</ul>}
  </div>
}

export function BriefDocument({ document, version }: { document: Document; version?: number }) {
  return <Card className="brief-document" aria-label="Executive report">
    <header className="brief-paper-header">
      <p className="brief-masthead">CampaignIQ <span> / </span> Northstar Outfitters</p>
      <h2>{document.title}</h2>
      <p>{dateRange(document.period.start, document.period.end)} · {version ? `Version ${version}` : "Draft preview"}</p>
      <p>Generated {timestamp.format(new Date(document.generated_at))} UTC · Fictional Northstar Outfitters</p>
      <p>{document.provenance}</p>
    </header>
    {document.sections.map(section => <section className="brief-section" key={section.title}>
      <h2>{section.title}</h2>
      {section.blocks.map((block, index) => <Content key={index} block={block} />)}
    </section>)}
  </Card>
}
