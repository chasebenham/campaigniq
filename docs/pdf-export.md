# PDF export

Open a saved brief or its selected historical version and click **Export PDF**. The file name is derived from the version's title and ends in `-vN.pdf`. The version must be specified in the API URL. Downloading from the listing exports the displayed saved version.

ReportLab builds Letter-size pages from the immutable document also used in the browser preview. The document uses a restrained CampaignIQ masthead, repeated table headers, consistent section hierarchy, source notes, and numbered footers. Actual spend trends are displayed as a table of observed reporting intervals. The export needs no external fonts, images, or services. Narrative text is escaped before rendering.

The saved provenance and limitations are printed with the report. If the live workspace later flags evidence as stale, the original PDF remains reproducible from that version. For an export that discusses refreshed evidence, explicitly save a new version first.

## Verification

The fictional November leadership report was exported from the production frontend through the versioned API. All five Letter-size pages were rendered to PNG and visually inspected. Review covered heading placement, wrapped text, table boundaries, page numbers, provenance, alignment, experiment labeling, and the historical and hypothetical cases. The final pagination kept each finding together and moved the findings heading onto the same page as its first finding.

Automated PDF tests extract the text from the file and compare expected financial values, historical commentary, dimensions, and filename. The PDF uses standard Latin-script typefaces. Multilingual typography and tagged archival PDFs are outside this template. [Sample report inputs](strategy-briefs.md) · [Verification commands](strategy-brief-tests.md)
